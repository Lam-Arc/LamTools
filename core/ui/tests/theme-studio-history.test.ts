import { beforeEach, describe, expect, it } from 'vitest'
import { createStudioStore } from '../src/themeStudio/store.ts'
import {
  THEME_HISTORY_LIMIT,
  loadHistory,
  pushHistory,
  summarizeHistoryEntry,
  type ThemeHistoryEntry,
  type ThemeHistoryStorage,
} from '../src/themeStudio/history.ts'
import {
  THEME_SAFE_MODE_KEY,
  applyStoredPublishedTheme,
  enterSafeThemeMode,
  isSafeThemeMode,
  recoverThemeStorage,
} from '../src/themeStudio/bootstrap.ts'
import { STUDIO_STYLE_ID } from '../src/themeStudio/runtime.ts'
import { THEME_STUDIO_DRAFT_STORAGE_KEY, THEME_STUDIO_STORAGE_KEY } from '../src/themeStudio/constants.ts'

/**
 * user:“主题保存、发布、回退和迁移”“保留上一版发布主题与版本历史”+
 * (发布不丢上一版；坏主题有与主题无关的恢复入口。)
 */

function fakeHistory(initial: unknown = null): ThemeHistoryStorage & { value: unknown } {
  const box = { value: initial }
  return {
    get value() { return box.value },
    set value(next: unknown) { box.value = next },
    read: () => box.value,
    write: (entries) => { box.value = entries },
  }
}

const container = () => document.createElement('div')

describe('发布历史', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  it('发布新版本时把上一版留进历史', () => {
    const root = container()
    const history = fakeHistory()
    const store = createStudioStore({ history, applyOptions: { container: root } })

    store.setNode('shell.sidebar', { spacing: { gap: 8 } })
    expect(store.publish().ok).toBe(true)
    expect(history.value).toBeNull() // 第一版没有「上一版」

    store.setNode('shell.sidebar', { spacing: { gap: 16 } })
    expect(store.publish().ok).toBe(true)

    const entries = store.history.value
    expect(entries).toHaveLength(1)
    expect(entries[0].document.nodes['shell.sidebar']?.spacing?.gap).toBe(8)
    expect(summarizeHistoryEntry(entries[0])).toContain('元素 1')
    store.dispose()
  })

  it('历史最多保留五版，最新在前', () => {
    const history = fakeHistory()
    const store = createStudioStore({ history, applyOptions: { container: container() } })
    for (let gap = 1; gap <= THEME_HISTORY_LIMIT + 3; gap += 1) {
      store.setNode('shell.sidebar', { spacing: { gap } })
      store.publish()
    }
    expect(store.history.value).toHaveLength(THEME_HISTORY_LIMIT)
    const gaps = store.history.value.map((entry) => entry.document.nodes['shell.sidebar']?.spacing?.gap)
    expect(gaps[0]).toBe(THEME_HISTORY_LIMIT + 2)
    store.dispose()
  })

  it('坏历史只丢那一条，不影响读取', () => {
    const good = {
      at: new Date().toISOString(),
      document: { schemaVersion: 1, themeId: 'studio', nodes: { 'shell.sidebar': { spacing: { gap: 8 } } }, templates: {}, instances: {}, breakpoints: [], variables: {}, assets: [] },
    }
    const storage = fakeHistory([{ at: 'bad', document: { nope: true } }, { at: 42 }, good])
    const entries = loadHistory(storage)
    expect(entries).toHaveLength(1)
    expect(entries[0].document.nodes['shell.sidebar']?.spacing?.gap).toBe(8)
  })

  it('回滚把那一版放回草稿，不动已发布主题', () => {
    const history = fakeHistory()
    const store = createStudioStore({ history, applyOptions: { container: container() } })
    store.setNode('shell.sidebar', { spacing: { gap: 8 } })
    store.publish()
    store.setNode('shell.sidebar', { spacing: { gap: 24 } })
    store.publish()
    const publishedGap = store.published.value.nodes['shell.sidebar']?.spacing?.gap
    expect(publishedGap).toBe(24)

    expect(store.restoreHistory(0)).toBe(true)
    expect(store.draft.value.nodes['shell.sidebar']?.spacing?.gap).toBe(8)
    expect(store.published.value.nodes['shell.sidebar']?.spacing?.gap).toBe(24)
    expect(store.dirty.value).toBe(true)
    store.dispose()
  })

  it('恢复默认同时清空历史', () => {
    const history = fakeHistory()
    const store = createStudioStore({ history, applyOptions: { container: container() } })
    store.setNode('shell.sidebar', { spacing: { gap: 8 } })
    store.publish()
    store.setNode('shell.sidebar', { spacing: { gap: 12 } })
    store.publish()
    expect(store.history.value).toHaveLength(1)

    store.reset()
    expect(store.history.value).toEqual([])
    expect(history.value).toEqual([])
    store.dispose()
  })

  it('空主题不占历史位', () => {
    const storage = fakeHistory()
    const entries = pushHistory(storage, { schemaVersion: 1, themeId: 'studio', nodes: {}, templates: {}, instances: {}, breakpoints: [], variables: {}, assets: [] } as never)
    expect(entries).toEqual([])
    expect(storage.value).toBeNull()
  })
})

describe('安全模式与恢复', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  it('URL 参数或本地标记都能打开安全模式', () => {
    expect(isSafeThemeMode({ search: '?safe-theme=1' })).toBe(true)
    expect(isSafeThemeMode({ search: '?safe-theme=0' })).toBe(false)
    expect(isSafeThemeMode({ search: '', readFlag: () => true })).toBe(true)
    expect(isSafeThemeMode({ search: '', readFlag: () => false })).toBe(false)
  })

  it('安全模式下启动不应用已发布主题', () => {
    const root = container()
    const document = { schemaVersion: 1, themeId: 'studio', nodes: { 'shell.sidebar': { spacing: { gap: 8 } } }, templates: {}, instances: {}, breakpoints: [], variables: {}, assets: [] }
    const applied = applyStoredPublishedTheme({ read: () => document, container: root, safeMode: () => true })
    expect(applied).toBe(false)
    expect(root.querySelector('style')).toBeNull()
  })

  it('一键恢复清掉已发布与草稿，历史保留', () => {
    localStorage.setItem(THEME_STUDIO_STORAGE_KEY, '{"schemaVersion":1}')
    localStorage.setItem(THEME_STUDIO_DRAFT_STORAGE_KEY, '{"schemaVersion":1}')
    localStorage.setItem('sunday.themeStudio.history.v1', JSON.stringify([{ at: new Date().toISOString(), document: { schemaVersion: 1 } }]))
    const root = document.createElement('div')
    const style = document.createElement('style')
    style.dataset.uiThemeStudio = STUDIO_STYLE_ID
    root.appendChild(style)

    recoverThemeStorage({ container: root })

    expect(localStorage.getItem(THEME_STUDIO_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(THEME_STUDIO_DRAFT_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem('sunday.themeStudio.history.v1')).toBeTruthy()
    expect(root.querySelectorAll('style').length).toBe(0)
  })

  it('进入安全模式会撤掉自定义样式并记住标记', () => {
    const root = document.createElement('div')
    const style = document.createElement('style')
    style.dataset.uiThemeStudio = STUDIO_STYLE_ID
    root.appendChild(style)

    enterSafeThemeMode({ container: root })

    expect(root.querySelectorAll('style').length).toBe(0)
    expect(localStorage.getItem(THEME_SAFE_MODE_KEY)).toBe('1')
    expect(isSafeThemeMode()).toBe(true)
  })
})
