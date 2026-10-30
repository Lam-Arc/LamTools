import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatOutlineNavigator from '../src/components/ChatOutlineNavigator.vue'
import {
  CHAT_OUTLINE_ACTIVATION_RATIO,
  CHAT_OUTLINE_PAGE_SIZE,
  bracketOutlineControls,
  buildOutlineCatalog,
  clampOutlinePage,
  compactOutlineMarkerPositions,
  filterOutlineCatalog,
  formatOutlineTimestamp,
  isGuideOutlineMessageId,
  loadedUserMessageSignature,
  nearestMountedOutlineIndex,
  nearestOutlineIndex,
  normalizeChatOutlinePayload,
  outlineCatalogBounds,
  outlineIndexFromScrollProgress,
  outlineMarkerHitRadius,
  outlineMarkerStyle,
  outlinePageCount,
  resolveOutlineSelectedIndex,
  sliceOutlinePage,
  sortOutlineCatalog,
  type ChatOutlineItem,
} from '../src/components/chatOutlineNavigator'
import type { CoreMessage } from '../src/types'

function message(id: string, role: CoreMessage['role'], content = id): CoreMessage {
  return { id, role, content, timestamp: '', parts: [] }
}

describe('ChatOutlineNavigator contracts', () => {
  const originalGetContext = HTMLCanvasElement.prototype.getContext

  beforeEach(() => {
    HTMLCanvasElement.prototype.getContext = (() => ({
      setTransform: vi.fn(),
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
    })) as unknown as typeof HTMLCanvasElement.prototype.getContext
  })

  afterEach(() => {
    HTMLCanvasElement.prototype.getContext = originalGetContext
  })

  it('normalizes the thread.outline contract and drops malformed rows', () => {
    expect(normalizeChatOutlinePayload({
      items: [
        { message_id: 'm2', turn_id: 't2', seq: 2, timestamp: '2', prompt: 'second', response_excerpt: 'reply' },
        { message_id: 'm1', turn_id: 't1', seq: 1, timestamp: '1', prompt: 'first', response_excerpt: '' },
        { turn_id: 'missing-id' },
        null,
      ],
    })).toEqual([
      { message_id: 'm1', turn_id: 't1', seq: 1, timestamp: '1', prompt: 'first', response_excerpt: '' },
      { message_id: 'm2', turn_id: 't2', seq: 2, timestamp: '2', prompt: 'second', response_excerpt: 'reply' },
    ])
  })

  it('uses only loaded user ids as the refresh signature', () => {
    const first = [message('u1', 'user', 'draft'), message('a1', 'assistant', 'streaming')]
    const sameIds = [message('u1', 'user', 'edited locally'), message('a1', 'assistant', 'new token')]
    const next = [...sameIds, message('u2', 'user')]
    expect(loadedUserMessageSignature(first)).toBe(loadedUserMessageSignature(sameIds))
    expect(loadedUserMessageSignature(next)).not.toBe(loadedUserMessageSignature(sameIds))
  })

  it('chooses the marker nearest the 38% activation geometry and shortens distant markers', () => {
    expect(CHAT_OUTLINE_ACTIVATION_RATIO).toBe(0.38)
    expect(nearestOutlineIndex([20, 80, 180], 68)).toBe(1)
    const selected = outlineMarkerStyle(1, 1, 4)
    const near = outlineMarkerStyle(0, 1, 4)
    const middle = outlineMarkerStyle(3, 1, 4)
    const far = outlineMarkerStyle(4, 1, 4)
    expect(selected.length).toBeGreaterThan(near.length)
    expect(near.length).toBeGreaterThan(middle.length)
    expect(middle.length).toBeGreaterThan(far.length)
    expect(selected.opacity).toBeGreaterThan(far.opacity)
    expect(resolveOutlineSelectedIndex(3, 2, true)).toBe(3)
    expect(resolveOutlineSelectedIndex(-1, 2, true)).toBe(2)
    expect(resolveOutlineSelectedIndex(-1, 2, false)).toBe(-1)
  })

  it('keeps short marker groups compact while active selection uses mounted card geometry', () => {
    expect(compactOutlineMarkerPositions(4, 100, 300, 8)).toEqual([238, 246, 254, 262])
    expect(compactOutlineMarkerPositions(4, 100, 24, 12)).toEqual([100, 108, 116, 124])
    expect(compactOutlineMarkerPositions(1, 100, 300, 12)).toEqual([250])
    expect(nearestMountedOutlineIndex([
      { index: 0, centerY: 180 },
      { index: 3, centerY: 320 },
    ], 305)).toBe(3)
    expect(outlineIndexFromScrollProgress(0, 1000, 200, 4)).toBe(0)
    expect(outlineIndexFromScrollProgress(400, 1000, 200, 4)).toBe(2)
    expect(outlineIndexFromScrollProgress(800, 1000, 200, 4)).toBe(3)
  })

  it('fetches per session and loaded-user signature, then supports keyboard selection', async () => {
    const thread = document.createElement('section')
    document.body.appendChild(thread)
    Object.defineProperty(thread, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 100, left: 0, width: 800, height: 500, right: 800, bottom: 600 }),
    })
    const requestRpc = vi.fn().mockResolvedValue({
      items: [
        { message_id: 'u1', turn_id: 't1', seq: 1, timestamp: '', prompt: 'first', response_excerpt: 'one' },
        { message_id: 'u2', turn_id: 't2', seq: 2, timestamp: '', prompt: 'second', response_excerpt: 'two' },
      ],
    })
    const wrapper = mount(ChatOutlineNavigator, {
      attachTo: document.body,
      props: {
        sessionId: 'session-1',
        messages: [message('u1', 'user'), message('a1', 'assistant')],
        requestRpc,
        scrollContainer: thread,
      },
    })
    await vi.waitFor(() => expect(requestRpc).toHaveBeenCalledWith('thread.outline', { thread_id: 'session-1' }))
    const root = wrapper.get('[data-chat-outline-navigator]')
    Object.defineProperty(root.element, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 0, left: 0, width: 32, height: 700, right: 32, bottom: 700 }),
    })
    const canvas = wrapper.get('canvas').element as HTMLCanvasElement
    Object.defineProperty(canvas, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 0, left: 0, width: 32, height: 700, right: 32, bottom: 700 }),
    })
    expect(wrapper.get('.chat-outline-navigator__status').text()).toBe('')

    root.element.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await vi.waitFor(() => expect(wrapper.get('.chat-outline-navigator__status').text()).toContain('共 2 条'))
    await root.trigger('keydown', { key: 'End' })
    await root.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')?.at(-1)).toEqual(['u2'])

    await wrapper.setProps({ messages: [message('u1', 'user'), message('a1', 'assistant', 'new token')] })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(requestRpc).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ messages: [message('u1', 'user'), message('a1', 'assistant', 'new token'), message('u2', 'user')] })
    await vi.waitFor(() => expect(requestRpc).toHaveBeenCalledTimes(2))
    wrapper.unmount()
    thread.remove()
  })

  it('ignores an older session response that resolves after a switch', async () => {
    const pending: Array<(value: Record<string, unknown>) => void> = []
    const requestRpc = vi.fn().mockImplementation(() => new Promise<Record<string, unknown>>(resolve => {
      pending.push(resolve)
    }))
    const thread = document.createElement('section')
    document.body.appendChild(thread)
    const wrapper = mount(ChatOutlineNavigator, {
      attachTo: document.body,
      props: {
        sessionId: 'old-session',
        messages: [message('u1', 'user')],
        requestRpc,
        scrollContainer: thread,
      },
    })
    await vi.waitFor(() => expect(requestRpc).toHaveBeenCalledTimes(1))
    await wrapper.setProps({ sessionId: 'new-session' })
    await vi.waitFor(() => expect(requestRpc).toHaveBeenCalledTimes(2))
    pending[0]({ items: [{ message_id: 'old-message', seq: 1, prompt: 'stale' }] })
    pending[1]({ items: [{ message_id: 'new-message', seq: 1, prompt: 'fresh' }] })
    await vi.waitFor(() => expect(wrapper.get('[data-chat-outline-navigator]')).toBeTruthy())
    await wrapper.get('[data-chat-outline-navigator]').trigger('focusin')
    await vi.waitFor(() => expect(wrapper.get('[data-chat-outline-preview]')).toBeTruthy())
    expect(wrapper.get('[data-chat-outline-preview]').text()).toContain('fresh')
    expect(wrapper.get('[data-chat-outline-preview]').text()).not.toContain('stale')
    wrapper.unmount()
    thread.remove()
  })

  it('cancels a pending geometry frame when unmounted', async () => {
    const requestRpc = vi.fn().mockResolvedValue({
      items: [{ message_id: 'u1', seq: 1, prompt: 'first' }],
    })
    const thread = document.createElement('section')
    document.body.appendChild(thread)
    const requestFrame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 241)
    const cancelFrame = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined)
    const wrapper = mount(ChatOutlineNavigator, {
      attachTo: document.body,
      props: {
        sessionId: 'session-1',
        messages: [message('u1', 'user')],
        requestRpc,
        scrollContainer: thread,
      },
    })
    await vi.waitFor(() => expect(requestFrame).toHaveBeenCalled())
    wrapper.unmount()
    expect(cancelFrame).toHaveBeenCalledWith(241)
    requestFrame.mockRestore()
    cancelFrame.mockRestore()
    thread.remove()
  })
})

describe('ChatOutlineNavigator paging and catalog', () => {
  it('pages 20 user messages at a time', () => {
    expect(CHAT_OUTLINE_PAGE_SIZE).toBe(20)
    expect(outlinePageCount(0)).toBe(1)
    expect(outlinePageCount(20)).toBe(1)
    expect(outlinePageCount(21)).toBe(2)
    expect(clampOutlinePage(9, 21)).toBe(1)
    expect(clampOutlinePage(-3, 21)).toBe(0)
    const indexes = Array.from({ length: 25 }, (_, index) => index)
    expect(sliceOutlinePage(indexes, 0)).toHaveLength(20)
    expect(sliceOutlinePage(indexes, 1)).toEqual([20, 21, 22, 23, 24])
  })

  it('separates guide instructions from ordinary prompts and orders them by time', () => {
    const items: ChatOutlineItem[] = [
      { message_id: 't1:user', turn_id: 't1', seq: 1, timestamp: '2026-10-01T10:00:00Z', prompt: 'first prompt', response_excerpt: 'a' },
      { message_id: 't1:user:guide:ev1', turn_id: 't1', seq: 2, timestamp: '2026-10-01T10:05:00Z', prompt: 'please also refactor', response_excerpt: 'b' },
      { message_id: 't2:user', turn_id: 't2', seq: 3, timestamp: '2026-10-01T10:10:00Z', prompt: 'second prompt', response_excerpt: 'c' },
    ]
    const entries = buildOutlineCatalog(items)
    expect(entries.map(entry => entry.isGuide)).toEqual([false, true, false])
    expect(entries.map(entry => entry.index)).toEqual([0, 1, 2])
    expect(filterOutlineCatalog(entries, 'REFACTOR').map(entry => entry.index)).toEqual([1])
    expect(filterOutlineCatalog(entries, '', 'guide').map(entry => entry.index)).toEqual([1])
    expect(filterOutlineCatalog(entries, '', 'normal').map(entry => entry.index)).toEqual([0, 2])
    expect(sortOutlineCatalog(entries, 'asc').map(entry => entry.index)).toEqual([0, 1, 2])
    expect(sortOutlineCatalog(entries, 'desc').map(entry => entry.index)).toEqual([2, 1, 0])
    expect(isGuideOutlineMessageId('t1:user:guide:ev1')).toBe(true)
    expect(isGuideOutlineMessageId('t1:user')).toBe(false)
  })

  it('formats catalog timestamps and tolerates rows without a time', () => {
    // 本地时间字符串让断言与机器时区无关。
    expect(formatOutlineTimestamp('', new Date('2026-10-02T00:00:00'))).toBe('')
    expect(formatOutlineTimestamp('not-a-date', new Date('2026-10-02T00:00:00'))).toBe('')
    expect(formatOutlineTimestamp('2026-10-01T10:05:00', new Date('2026-10-01T12:00:00')))
      .toBe('10:05')
    expect(formatOutlineTimestamp('2026-10-01T10:05:00', new Date('2026-12-24T12:00:00')))
      .toBe('10-01 10:05')
  })

  it('pages the rail, opens the catalog card and jumps to a chosen message', async () => {
    const thread = document.createElement('section')
    document.body.appendChild(thread)
    const items = Array.from({ length: 25 }, (_, index) => ({
      message_id: index === 21 ? 'turn-21:user:guide:ev' : `u-${index}`,
      turn_id: `t-${index}`,
      seq: index + 1,
      timestamp: new Date(Date.UTC(2026, 9, 1, 10, index)).toISOString(),
      prompt: `prompt ${index}`,
      response_excerpt: '',
    }))
    const requestRpc = vi.fn().mockResolvedValue({ items })
    const wrapper = mount(ChatOutlineNavigator, {
      attachTo: document.body,
      props: {
        sessionId: 'session-1',
        messages: [message('u-0', 'user')],
        requestRpc,
        scrollContainer: thread,
      },
    })

    await vi.waitFor(() => expect(wrapper.find('[data-chat-outline-page-indicator]').exists()).toBe(true))
    expect(wrapper.get('[data-chat-outline-page-indicator]').text()).toBe('1/2')
    // user:“上下键不是始终显示，有能往上翻再显示上键 能往下翻再显示下键”
    // (第一页没有上一页 → 上键不出现；还能往后翻 → 下键出现)
    expect(wrapper.find('[data-chat-outline-page-up]').exists()).toBe(false)
    expect(wrapper.find('[data-chat-outline-page-down]').exists()).toBe(true)

    await wrapper.get('[data-chat-outline-page-down]').trigger('click')
    expect(wrapper.get('[data-chat-outline-page-indicator]').text()).toBe('2/2')
    // 最后一页 → 下键消失，上键出现。
    expect(wrapper.find('[data-chat-outline-page-down]').exists()).toBe(false)
    expect(wrapper.find('[data-chat-outline-page-up]').exists()).toBe(true)

    // 底部「目录」按钮展开目录卡片，并按原始序号列出全部用户消息。
    await wrapper.get('[data-chat-outline-catalog-toggle]').trigger('click')
    expect(wrapper.get('[data-chat-outline-catalog-count]').text()).toBe('25/25')
    expect(wrapper.findAll('[data-chat-outline-catalog-item]')).toHaveLength(25)
    expect(wrapper.findAll('[data-chat-outline-catalog-item]')[0]
      .attributes('data-chat-outline-catalog-item')).toBe('u-0')

    // 时间排序：倒序后最新的一条排在最前。
    await wrapper.get('[data-chat-outline-catalog-sort]').trigger('click')
    expect(wrapper.findAll('[data-chat-outline-catalog-item]')[0]
      .attributes('data-chat-outline-catalog-item')).toBe('u-24')

    // 关键词搜索。
    await wrapper.get('[data-chat-outline-catalog-search]').setValue('prompt 5')
    expect(wrapper.findAll('[data-chat-outline-catalog-item]')).toHaveLength(1)

    // 类型筛选：只留引导消息。
    await wrapper.get('[data-chat-outline-catalog-search]').setValue('')
    await wrapper.get('[data-chat-outline-catalog-kind="guide"]').trigger('click')
    const guides = wrapper.findAll('[data-chat-outline-catalog-item]')
    expect(guides).toHaveLength(1)
    expect(guides[0].text()).toContain('引导')

    // 点击目录项跳转到对应消息并收起卡片。
    await guides[0].trigger('click')
    expect(wrapper.emitted('select')?.at(-1)).toEqual(['turn-21:user:guide:ev'])
    expect(wrapper.find('[data-chat-outline-catalog]').exists()).toBe(false)

    wrapper.unmount()
    thread.remove()
  })

  it('keeps the catalog card above the composer and shrinks it on short viewports', () => {
    // 800 高的消息区、底部控件组底边在 700：卡片底边距栏底 100，最多向上长 692。
    expect(outlineCatalogBounds(800, 700, 8)).toEqual({ bottom: 100, maxHeight: 692 })
    // 窗口变矮时可用高度跟着缩，卡片不会伸进输入栏。
    expect(outlineCatalogBounds(400, 300, 8)).toEqual({ bottom: 100, maxHeight: 292 })
    // 尚未测量时退回一个间距，且不产生负高度。
    expect(outlineCatalogBounds(0, 0, 8)).toEqual({ bottom: 8, maxHeight: 0 })
  })

  it('tightens each marker hit box to half of the smallest gap', () => {
    // 8px 间距 → 判定半径 4px；压缩到 2px 间距时不低于 2px，单条标记取 6px 上限。
    expect(outlineMarkerHitRadius([200, 208, 216])).toBe(4)
    expect(outlineMarkerHitRadius([200, 202, 210])).toBe(2)
    expect(outlineMarkerHitRadius([200])).toBe(6)
    expect(outlineMarkerHitRadius([])).toBe(6)
  })

  it('brackets the pager stacks against the first and last marker', () => {
    // 上箭头在第一条标记上方，下箭头/目录/页码在最后一条标记下方。
    expect(bracketOutlineControls([200, 208, 216], 8, 20, 60, 600))
      .toEqual({ top: 172, bottom: 224 })
    expect(bracketOutlineControls([300], 12, 20, 60, 600))
      .toEqual({ top: 268, bottom: 312 })
    // 标记贴近底部时，底部控件组整体上移，避免超出左栏。
    expect(bracketOutlineControls([580], 8, 20, 60, 600))
      .toEqual({ top: 552, bottom: 540 })
    expect(bracketOutlineControls([], 8, 20, 60, 600))
      .toEqual({ top: 8, bottom: 8 })
  })

  it('puts the up arrow above the rail and stacks down arrow, catalog icon and page number below', async () => {
    const thread = document.createElement('section')
    document.body.appendChild(thread)
    const items = Array.from({ length: 25 }, (_, index) => ({
      message_id: `u-${index}`,
      turn_id: `t-${index}`,
      seq: index + 1,
      timestamp: new Date(Date.UTC(2026, 9, 1, 10, index)).toISOString(),
      prompt: `prompt ${index}`,
      response_excerpt: '',
    }))
    const wrapper = mount(ChatOutlineNavigator, {
      attachTo: document.body,
      props: {
        sessionId: 'session-1',
        messages: [message('u-0', 'user')],
        requestRpc: vi.fn().mockResolvedValue({ items }),
        scrollContainer: thread,
      },
    })

    await vi.waitFor(() => expect(wrapper.find('[data-chat-outline-page-indicator]').exists()).toBe(true))

    // 第一页没有上翻内容：上键不显示；底部顺序必须是：下箭头 → 目录 → 页码。
    const topControls = wrapper.get('.chat-outline-navigator__controls--top')
    expect(topControls.find('[data-chat-outline-page-up]').exists()).toBe(false)
    expect(topControls.find('[data-chat-outline-page-down]').exists()).toBe(false)

    const bottomOrder = () => {
      const bottomControls = wrapper.get('.chat-outline-navigator__controls--bottom')
      return Array.from(bottomControls.element.children).map((child) => {
        if (child.hasAttribute('data-chat-outline-page-down')) return 'down'
        if (child.hasAttribute('data-chat-outline-catalog-toggle')) return 'catalog'
        if (child.hasAttribute('data-chat-outline-page-indicator')) return 'page'
        return 'other'
      })
    }
    expect(bottomOrder()).toEqual(['down', 'catalog', 'page'])

    // 翻到下一页后：上键出现在标记组上方，下键消失，目录/页码保持原位。
    await wrapper.get('[data-chat-outline-page-down]').trigger('click')
    expect(wrapper.get('.chat-outline-navigator__controls--top').find('[data-chat-outline-page-up]').exists()).toBe(true)
    expect(wrapper.find('[data-chat-outline-page-down]').exists()).toBe(false)
    expect(bottomOrder()).toEqual(['catalog', 'page'])

    // 目录键只显示图标，文字仅保留在无障碍名称里。
    const catalogToggle = wrapper.get('[data-chat-outline-catalog-toggle]')
    expect(catalogToggle.text()).toBe('')
    expect(catalogToggle.find('svg').exists()).toBe(true)
    expect(catalogToggle.attributes('aria-label')).toBe('展开目录')

    wrapper.unmount()
    thread.remove()
  })
})
