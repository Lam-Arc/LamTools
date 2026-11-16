import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import ChatThread from '../src/components/ChatThread.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

/**
 * user:“把会话内过程行改造成「折叠态 → 一级展开 → 二级展开」三段式渐进披露，并修掉三个交互缺陷”+
 * (覆盖：preview↔expanded 循环、划选不切换、位移 <4px 才切换、默认变量下 6/10 行、
 *  遮罩只在溢出时出现、暂停态不折叠、running 时一级展开锚定底部。)
 */

const __dirname = dirname(fileURLToPath(import.meta.url))
const testTransport = createFakeTransport()
const PROCESS_CSS = readFileSync(resolve(__dirname, '../src/styles/chat-thread-process.css'), 'utf8')

function mountChatThread(options: any = {}) {
  return mount(ChatThread, {
    ...options,
    props: { transport: testTransport, ...(options.props ?? {}) },
  })
}

function reasoningMessage(options: { status?: string; turnStatus?: string; live?: boolean } = {}): CoreMessage {
  return {
    id: 'm-process-rows',
    role: 'assistant',
    content: '',
    timestamp: '2026-06-18T00:00:00.000Z',
    metadata: {
      live: options.live ?? true,
      timeline: true,
      ...(options.turnStatus ? { turnStatus: options.turnStatus } : {}),
    },
    parts: [{
      id: 'p-process-rows',
      partType: 'reasoning',
      status: options.status ?? 'completed',
      label: '思考',
      content: ['第一行', '第二行', '第三行', '第四行', '第五行', '第六行', '第七行', '第八行'].join('\n'),
    }],
  } as CoreMessage
}

/** 点标题栏进入一级展开，返回正文节点。 */
async function openFirstStage(wrapper: any) {
  await wrapper.find('.reasoning-toggle').trigger('click')
  const body = wrapper.find('.reasoning-body')
  expect(body.exists()).toBe(true)
  return body
}

/** 从 CSS 里取一条规则（这些规则体内没有嵌套花括号）。 */
function ruleOf(selector: string): string {
  const start = PROCESS_CSS.indexOf(selector)
  if (start < 0) return ''
  const end = PROCESS_CSS.indexOf('}', start)
  return PROCESS_CSS.slice(start, end + 1)
}

class FakeResizeObserver {
  static instances: FakeResizeObserver[] = []
  callback: () => void
  targets: HTMLElement[] = []

  constructor(callback: () => void) {
    this.callback = callback
    FakeResizeObserver.instances.push(this)
  }

  observe(target: HTMLElement) {
    this.targets.push(target)
  }

  unobserve() {}

  disconnect() {
    this.targets = []
  }
}

function measureAll() {
  for (const observer of FakeResizeObserver.instances) observer.callback()
}

/** jsdom 没有布局：手动给出滚动尺寸，让「是否溢出」可判定。 */
function stubScrollMetrics(el: HTMLElement, scrollHeight: number, clientHeight: number, scrollTop = 0) {
  Object.defineProperty(el, 'scrollHeight', { configurable: true, value: scrollHeight })
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: clientHeight })
  Object.defineProperty(el, 'scrollTop', { configurable: true, writable: true, value: scrollTop })
}

describe('process row three-stage disclosure', () => {
  beforeEach(() => {
    FakeResizeObserver.instances = []
    ;(globalThis as any).ResizeObserver = FakeResizeObserver
  })

  afterEach(() => {
    delete (globalThis as any).ResizeObserver
    FakeResizeObserver.instances = []
  })

  it('cycles preview → expanded → preview from the body and folds back to one line from the header', async () => {
    const wrapper = mountChatThread({ props: { messages: [reasoningMessage()] } })

    let body = await openFirstStage(wrapper)
    expect(body.classes()).toContain('process-card-body--preview')

    await body.trigger('click')
    body = wrapper.find('.reasoning-body')
    expect(body.classes()).toContain('process-card-body--expanded')

    // 再点内容区：收起回一级（6 行），不是只升不降
    await body.trigger('click')
    body = wrapper.find('.reasoning-body')
    expect(body.classes()).toContain('process-card-body--preview')

    // 点标题栏：直接折叠回单行
    await wrapper.find('.reasoning-toggle').trigger('click')
    expect(wrapper.find('.reasoning-body').exists()).toBe(false)
  })

  it('ignores a click that lands while text is selected', async () => {
    const wrapper = mountChatThread({ props: { messages: [reasoningMessage()] } })
    const body = await openFirstStage(wrapper)
    const original = window.getSelection
    window.getSelection = (() => ({ toString: () => '被选中的一段思考内容' })) as unknown as typeof window.getSelection
    try {
      await body.trigger('click')
    } finally {
      window.getSelection = original
    }
    expect(wrapper.find('.reasoning-body').classes()).toContain('process-card-body--preview')
  })

  it('only toggles when the pointer moved less than 4px', async () => {
    const wrapper = mountChatThread({ props: { messages: [reasoningMessage()] } })

    async function dragBy(dx: number, dy: number) {
      const el = wrapper.find('.reasoning-body').element
      el.dispatchEvent(new MouseEvent('pointerdown', { clientX: 100, clientY: 100, bubbles: true }))
      await wrapper.find('.reasoning-body').trigger('click', { clientX: 100 + dx, clientY: 100 + dy })
    }

    await openFirstStage(wrapper)
    // 拖动划选（位移 30px）：不切换
    await dragBy(30, 0)
    expect(wrapper.find('.reasoning-body').classes()).toContain('process-card-body--preview')

    // 位移 1px 的普通点击：切换
    await dragBy(1, 0)
    expect(wrapper.find('.reasoning-body').classes()).toContain('process-card-body--expanded')
  })

  it('sizes both stages from the shared variables with 6/10 line defaults', () => {
    const previewRule = ruleOf('.thread .reasoning-body.process-card-body--preview {')
    const expandedRule = ruleOf('.thread .reasoning-body.process-card-body--expanded {')
    // user:“鼠标 hover 和不 hover 它的长度不一样”+(悬停增高整条规则已移除，高度只由
    // 一级/二级展开决定，这里断言它不会回来。)
    const hoverRule = ruleOf('.thread .reasoning-body.process-card-body--expanded:hover {')
    const toolBodyRule = ruleOf('.tool-card-body.process-card-body--preview,')

    expect(previewRule).toContain('var(--ms-proc-lines-1, 6)')
    expect(previewRule).toContain('var(--ms-proc-body-line-height, 1.65)')
    expect(previewRule).toContain('var(--ms-proc-body-pad-y, 10px)')
    expect(previewRule).toContain('var(--ms-proc-body-font-size, 12px)')
    expect(previewRule).toContain('overflow: auto')

    expect(expandedRule).toContain('var(--ms-proc-lines-2, 10)')
    expect(expandedRule).toContain('transition: max-height 200ms')

    // 已展开时悬停临时长到 15 行的规则必须保留
    expect(hoverRule).toBe('')

    // 工具正文原来写死的 800px 上限改成按行数算
    expect(toolBodyRule).toContain('var(--ms-proc-lines-1, 6)')
    expect(PROCESS_CSS).not.toContain('max-height: 800px')
  })

  it('adds the bottom fade mask only while a first-stage body actually overflows', async () => {
    const wrapper = mountChatThread({ props: { messages: [reasoningMessage()] } })
    const body = await openFirstStage(wrapper)
    const el = body.element as HTMLElement

    // 未溢出：不加遮罩
    stubScrollMetrics(el, 120, 120)
    measureAll()
    await nextTick()
    expect(wrapper.find('.reasoning-body').classes()).not.toContain('process-card-body--masked')

    // 内容溢出：加遮罩
    stubScrollMetrics(el, 400, 120)
    measureAll()
    await nextTick()
    expect(wrapper.find('.reasoning-body').classes()).toContain('process-card-body--masked')

    // 二级展开不加遮罩（哪怕内容还是溢出）
    await wrapper.find('.reasoning-body').trigger('click')
    await nextTick()
    const expanded = wrapper.find('.reasoning-body')
    expect(expanded.classes()).toContain('process-card-body--expanded')
    expect(expanded.classes()).not.toContain('process-card-body--masked')

    // 遮罩样式只在遮罩类上出现
    expect(ruleOf('.thread .process-card-body--masked {')).toContain('mask-image: linear-gradient(to bottom')
  })

  it('follows the newest line while a running first-stage body streams, until the reader scrolls up', async () => {
    const wrapper = mountChatThread({ props: { messages: [reasoningMessage({ status: 'running' })] } })
    const body = await openFirstStage(wrapper)
    const el = body.element as HTMLElement

    stubScrollMetrics(el, 600, 120, 0)
    measureAll()
    await nextTick()
    expect(el.scrollTop).toBe(600)

    // 用户上滚 200px：解除锚定，不再强行拉回
    el.scrollTop = 400
    await wrapper.find('.reasoning-body').trigger('scroll')
    measureAll()
    await nextTick()
    expect(el.scrollTop).toBe(400)

    // 滚回底部 24px 以内：恢复锚定
    el.scrollTop = 480
    await wrapper.find('.reasoning-body').trigger('scroll')
    measureAll()
    await nextTick()
    expect(el.scrollTop).toBe(600)
  })

  it('drives the body padding from --ms-proc-body-pad-y instead of only the height formula', () => {
    const previewRule = ruleOf('.thread .reasoning-body.process-card-body--preview {')
    const expandedRule = ruleOf('.thread .reasoning-body.process-card-body--expanded {')
    const toolBodyRule = ruleOf('.tool-card-body.process-card-body--preview,')

    // 高度先吃设置项的真源变量，没有才回落到行数公式
    expect(previewRule).toContain('max-height: var(--ms-proc-height-1,')
    expect(expandedRule).toContain('max-height: var(--ms-proc-height-2,')
    expect(toolBodyRule).toContain('max-height: var(--ms-proc-height-1,')

    // pad-y 真正驱动上下内边距，而不只是进高度公式
    expect(previewRule).toContain('padding-top: var(--ms-proc-body-pad-y, 10px)')
    expect(previewRule).toContain('padding-bottom: var(--ms-proc-body-pad-y, 10px)')
    expect(toolBodyRule).toContain('padding-top: var(--ms-proc-body-pad-y, 10px)')

    // 高度公式里已经含 2×pad-y：正文里再出现两次（padding-top / padding-bottom），合计 3 次
    expect(previewRule.split('var(--ms-proc-body-pad-y, 10px)').length - 1).toBe(3)
  })

  it('shows the expand chevron in the collapsed header and rotates it with the expanded class', async () => {
    const wrapper = mountChatThread({ props: { messages: [reasoningMessage()] } })

    const collapsed = wrapper.find('.process-card-chevron')
    expect(collapsed.exists()).toBe(true)
    expect(collapsed.classes()).not.toContain('is-expanded')

    await wrapper.find('.reasoning-toggle').trigger('click')
    expect(wrapper.find('.process-card-chevron').classes()).toContain('is-expanded')

    // 旋转 90° 由 is-expanded 驱动；尺寸 13、颜色跟随文字色，不做 hover 额外效果
    expect(ruleOf('.process-card-chevron.is-expanded {')).toContain('rotate(90deg)')
    expect(ruleOf('.process-card-chevron {')).toContain('width: 13px')
    expect(ruleOf('.process-card-chevron {')).toContain('color: currentColor')
  })

  it('keeps the process area unfolded while the turn is paused', () => {
    const paused = mountChatThread({
      props: { messages: [reasoningMessage({ live: false, turnStatus: 'paused' })] },
    })
    // 暂停/中断/失败都不折：过程区直接摊开（折叠态只有摘要条，没有 .process-stream）
    expect(paused.find('.process-stream').exists()).toBe(true)

    // 对照组：正常完成才折
    const completed = mountChatThread({
      props: { messages: [reasoningMessage({ live: false, turnStatus: 'completed' })] },
    })
    expect(completed.find('.process-summary').exists()).toBe(true)
    expect(completed.find('.process-stream').exists()).toBe(false)
  })
})
