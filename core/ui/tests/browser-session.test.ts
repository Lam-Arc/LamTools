import { describe, expect, it } from 'vitest'
import {
  browserProfileKey,
  isTemporaryProfile,
  permissionLabel,
  permissionPromptTitle,
  permissionResultText,
  profileBadge,
  profileOptions,
  profileRestoreNote,
  restoresOnRestart,
  siteDataHost,
  siteDataKindsArg,
  SITE_DATA_CACHE_TARGETS,
  SITE_DATA_STORAGE_TARGETS,
  siteDataSummary,
  downloadApprovalText,
  downloadStateLabel,
  downloadSummary,
} from '../src/split/browserSession'
import { restoreSplitState, sameTab, type SplitState } from '../src/workspace/types'
import { browserTabIcon, browserTabInitial, forgetBrowserTabIcon, setBrowserTabIcon } from '../src/split/browserIcons'

// user:“会话三态与恢复策略”+(前端只做显示与选择；这里盯住「临时标签不恢复」和「同址不同会话不合并」两条)。
describe('browser session profiles', () => {
  it('treats a missing profile as normal', () => {
    expect(browserProfileKey({})).toBe('normal')
    expect(browserProfileKey({ profile: '   ' })).toBe('normal')
    expect(browserProfileKey({ profile: 'incognito' })).toBe('incognito')
  })

  it('never restores temporary tabs but restores normal and custom ones', () => {
    expect(isTemporaryProfile('incognito')).toBe(true)
    expect(restoresOnRestart('incognito')).toBe(false)
    expect(restoresOnRestart(undefined)).toBe(true)
    expect(restoresOnRestart('normal')).toBe(true)
    // 自定义目录是命名 profile：会持久化，按 URL 恢复，并标注目录
    expect(restoresOnRestart('custom:webview2/temp-7')).toBe(true)
    expect(profileRestoreNote('custom:webview2/temp-7')).toBe('webview2/temp-7')
    expect(profileRestoreNote('normal')).toBeNull()
  })

  it('shows a badge only for non-normal sessions', () => {
    expect(profileBadge(undefined)).toBe('')
    expect(profileBadge('normal')).toBe('')
    expect(profileBadge('incognito')).toBe('临时')
    expect(profileBadge('custom:webview2/temp-7')).toBe('目录 temp-7')
  })

  it('greys out the temporary entry when it is unavailable', () => {
    const available = profileOptions(true)
    expect(available.map(option => option.kind)).toEqual(['normal', 'incognito'])
    expect(available.every(option => option.available)).toBe(true)
    const unavailable = profileOptions(false)
    expect(unavailable[1].available).toBe(false)
    expect(unavailable[1].hint).toContain('不可用')
  })

  it('keeps same-url tabs apart when their sessions differ', () => {
    const base = { id: 'a', kind: 'browser' as const, title: 'A', resource: 'https://example.com/' }
    // user:“临时标签与普通标签互不影响”+(同一个地址、不同会话必须是两个标签)
    expect(sameTab(base, { ...base, id: 'b' })).toBe(true)
    expect(sameTab(base, { ...base, id: 'b', profile: 'incognito' })).toBe(false)
    expect(sameTab({ ...base, profile: 'incognito' }, { ...base, id: 'b', profile: 'incognito' })).toBe(true)
  })
})

// user:“重启恢复：临时标签不恢复”+(布局模型是恢复的唯一入口；浏览器标签挂在辅助分屏里，主区不带标签)。
describe('split layout restore with sessions', () => {
  function stateWith(ids: Array<{ id: string; profile?: string }>): string {
    return JSON.stringify({
      version: 1,
      tree: {
        type: 'split',
        id: 'split-root',
        direction: 'columns',
        ratio: 0.6,
        first: { type: 'pane', id: 'main' },
        second: { type: 'pane', id: 'p1' },
      },
      panes: {
        p1: {
          id: 'p1',
          activeTab: ids[0]?.id ?? '',
          tabs: ids.map(tab => ({
            id: tab.id,
            kind: 'browser',
            title: tab.id,
            resource: `https://example.com/${tab.id}`,
            ...(tab.profile ? { profile: tab.profile } : {}),
          })),
        },
      },
      activePane: 'p1',
      hidden: false,
      focused: null,
    })
  }

  function browserTabIds(state: SplitState): string[] {
    return state.panes.p1?.tabs.map(tab => tab.id) ?? []
  }

  it('drops temporary tabs and keeps the rest', () => {
    const restored = restoreSplitState(stateWith([{ id: 'keep' }, { id: 'temp', profile: 'incognito' }, { id: 'custom', profile: 'custom:webview2/temp-2' }]))
    expect(browserTabIds(restored)).toEqual(['keep', 'custom'])
    // 活动标签是临时标签时，恢复后要落回第一个可恢复的标签
    const activeTemporary = restoreSplitState(stateWith([{ id: 'temp', profile: 'incognito' }, { id: 'keep' }]))
    expect(activeTemporary.panes.p1.activeTab).toBe('keep')
  })

  it('drops every temporary tab instead of keeping an empty pane', () => {
    const restored = restoreSplitState(stateWith([{ id: 'temp', profile: 'incognito' }]))
    expect(browserTabIds(restored)).toEqual([])
  })

  it('rejects a corrupted profile field instead of restoring it', () => {
    const raw = stateWith([{ id: 'a' }]).replace('"resource":"https://example.com/a"', '"resource":"https://example.com/a","profile":42')
    const restored = restoreSplitState(raw)
    // 整份布局校验失败 → 回到空布局，不带着非法字段恢复
    expect(browserTabIds(restored)).toEqual([])
    expect(restored.panes.p1).toBeUndefined()
  })
})

describe('site data clearing', () => {
  it('extracts the host from the address bar value', () => {
    expect(siteDataHost('https://Example.COM:8443/login?x=1')).toBe('example.com')
    expect(siteDataHost('http://localhost:5173/')).toBe('localhost')
    expect(siteDataHost('')).toBe('')
    expect(siteDataHost('not a url')).toBe('')
  })

  it('clears only storage targets and never cache targets', () => {
    // user:“站数据清理只清存储，缓存不动”+(清理请求里不允许出现任何缓存类目标)。
    const kinds = siteDataKindsArg()
    expect(kinds).toEqual(['cookies', 'storage'])
    for (const cache of SITE_DATA_CACHE_TARGETS) {
      expect(kinds).not.toContain(cache)
      expect(SITE_DATA_STORAGE_TARGETS).not.toContain(cache)
    }
    expect(SITE_DATA_STORAGE_TARGETS).toEqual(['cookies', 'local_storage', 'indexed_db', 'service_worker'])
  })

  it('says out loud that cache is left untouched', () => {
    const text = siteDataSummary('example.com')
    expect(text).toContain('example.com')
    expect(text).toContain('Service Worker')
    expect(text).toContain('缓存资源未清理')
    expect(text).not.toContain('与缓存，')
  })
})

describe('permission prompts', () => {
  it('names the permission in Chinese and never shows a raw key', () => {
    expect(permissionLabel('camera')).toBe('摄像头')
    expect(permissionLabel('clipboard_read')).toBe('剪贴板内容')
    expect(permissionLabel('something_new')).toBe('未知权限')
  })

  it('says who wants what', () => {
    const request = { host: 'example.com', kind: 'geolocation', message: 'raw' }
    expect(permissionPromptTitle(request)).toBe('example.com 想要使用位置信息')
  })

  it('keeps a visible result for both allow and deny', () => {
    const request = { host: 'example.com', kind: 'microphone', message: 'raw' }
    expect(permissionResultText(request, 'deny', 'once')).toContain('已拒绝')
    expect(permissionResultText(request, 'allow', 'once')).toContain('本次')
    expect(permissionResultText(request, 'allow', 'site')).toContain('长期')
  })
})

// user:“favicon 进标签栏”+(图标 store 与首字母占位都是纯逻辑，这里直接断言退化顺序的最后一级)。
describe('tab strip icons', () => {
  it('stores and clears a tab icon', () => {
    setBrowserTabIcon('tab-a', 'data:image/png;base64,AAA')
    expect(browserTabIcon('tab-a')).toBe('data:image/png;base64,AAA')
    // 换到没有图标的站点时不能残留上一个站点的图标
    setBrowserTabIcon('tab-a', null)
    expect(browserTabIcon('tab-a')).toBeUndefined()
    setBrowserTabIcon('tab-b', 'data:image/png;base64,BBB')
    forgetBrowserTabIcon('tab-b')
    expect(browserTabIcon('tab-b')).toBeUndefined()
  })

  it('falls back to the first letter of the title', () => {
    expect(browserTabInitial('example.com')).toBe('E')
    expect(browserTabInitial('  知乎')).toBe('知')
    expect(browserTabInitial('')).toBe('•')
    expect(browserTabInitial('!!!')).toBe('•')
  })
})

// user:“下载只做开始/完成/失败三态”+(文案里不能出现进度、暂停、继续这些我们并不支持的说法)。
describe('download list wording', () => {
  const base = { id: 'd1', tab: 't1', url: 'https://example.com/a.zip', filename: 'a.zip', path: 'C:/Downloads/Sunday/a.zip', needsApproval: false, startedAt: '2026-11-16T00:00:00Z' }

  it('labels exactly the three states', () => {
    expect(downloadStateLabel('started')).toBe('下载中')
    expect(downloadStateLabel('finished')).toBe('已完成')
    expect(downloadStateLabel('failed')).toBe('失败')
    for (const state of ['started', 'finished', 'failed'] as const) {
      const label = downloadStateLabel(state)
      for (const banned of ['%', '暂停', '继续']) expect(label).not.toContain(banned)
    }
  })

  it('summarises the list without inventing progress', () => {
    expect(downloadSummary([])).toBe('还没有下载')
    expect(downloadSummary([{ ...base, state: 'finished' }])).toBe('1 个已完成')
    expect(downloadSummary([{ ...base, state: 'started' }, { ...base, id: 'd2', state: 'finished' }])).toBe('1 个正在下载，1 个已完成')
  })

  it('explains why a dangerous file needs confirmation', () => {
    const text = downloadApprovalText({ ...base, filename: 'setup.exe', needsApproval: true })
    expect(text).toContain('setup.exe')
    expect(text).toContain('可执行')
  })
})
