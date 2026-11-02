/**
 * Ping 会话卡片与主界面行为同源验收。
 *
 * user:“全部都不要新建，样式待会单独说明，现在先去给其他的对齐”
 * +(会话卡片的行为——审批映射、消息渲染、输入区、分叉/回退/编辑——必须复用
 *   主内容区已有的实现，不允许在卡片里再维护一套简化版；样式本轮不动。)
 *
 * 两个层面：
 *  1. 源码契约：SessionCard 引用主界面同款组件（ChatThread / ComposerBar /
 *     InlineFileComposer / CoreSendStopButton），不再有手写审批映射与裸 textarea；
 *     SessionChannel 装配共享的投影控制器与审批控制器。
 *  2. 行为：通道上的决策提交走共享映射（approve → approve_once）、重复提交被去重、
 *     文本型决策走正常发送；分叉/回退用与主界面同一条线协议（session.fork /
 *     session.rollback）。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { resolve } from 'node:path'
import ChatThread from '../src/components/ChatThread.vue'
import SessionCard from '../src/pet/ui/SessionCard.vue'
import { SessionChannel } from '../src/pet/agent/host.ts'
import type { CoreDecisionSelectionPayload } from '../src/appServer/workbenchActions.ts'
import type { LamToolsTransport, TransportConnectionState, TransportMessage, TransportRequest } from '../src/transport/types'
import type { PetAgentClient } from '../src/pet/agent/client.ts'
import type { CardState, PingRuntime } from '../src/pet/ping/usePingRuntime.ts'

const uiRoot = resolve(import.meta.dirname, '../src')

afterEach(() => {
  // 主题测试会写 :root 与 localStorage，逐条清理，避免串扰其它用例。
  document.documentElement.removeAttribute('style')
  localStorage.clear()
})

// ---------------------------------------------------------------------------
// 伪造传输：记录每个 RPC 并按方法返回脚本化响应。
// ---------------------------------------------------------------------------
class ScriptedRpcTransport implements LamToolsTransport {
  readonly calls: { method: string; params: Record<string, unknown> }[] = []
  readonly handlers = new Map<string, (params: Record<string, unknown>) => Promise<Record<string, unknown>> | Record<string, unknown>>()
  private readonly messageListeners = new Set<(message: TransportMessage) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()

  async connect(): Promise<void> {
    for (const listener of this.stateListeners) listener('connected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    if (request.kind === 'http') return { status: 200, headers: {}, body: new Uint8Array() } as TResponse
    const params = (request.params || {}) as Record<string, unknown>
    this.calls.push({ method: request.method, params })
    const handler = this.handlers.get(request.method)
    return (handler ? await handler(params) : { method: request.method }) as TResponse
  }

  send(): void {}
  subscribe(listener: (message: TransportMessage) => void): () => void {
    this.messageListeners.add(listener)
    return () => this.messageListeners.delete(listener)
  }
  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }
  close(): void {
    for (const listener of this.stateListeners) listener('disconnected')
  }
  getState(): TransportConnectionState { return 'connected' }

  methods(): string[] { return this.calls.map(call => call.method) }
  paramsOf(method: string): Record<string, unknown> {
    const found = [...this.calls].reverse().find(call => call.method === method)
    return found?.params || {}
  }
}

function makeTransport(): ScriptedRpcTransport {
  const transport = new ScriptedRpcTransport()
  transport.handlers.set('initialize', () => ({ capabilities: {} }))
  transport.handlers.set('thread/read', () => ({}))
  transport.handlers.set('thread/resume', () => ({}))
  transport.handlers.set('approval/respond', () => ({ ok: true }))
  transport.handlers.set('turn/start', () => ({ ok: true }))
  transport.handlers.set('session.fork', () => ({ session_id: 'fork-9' }))
  transport.handlers.set('session.rollback', () => ({}))
  return transport
}

function makeClient(transport: ScriptedRpcTransport): PetAgentClient {
  return {
    apiBase: 'http://pet.test',
    transport: { fork: () => transport } as unknown as PetAgentClient['transport'],
    projects: {} as never,
    listSessions: async () => [],
    createSession: async () => ({ id: 's1', title: 't', projectId: 'p1' }),
    ensureFallbackSession: async () => ({ projectId: 'p1', sessionId: 's1', created: true }),
    ensureProjectSession: async () => ({ projectId: 'p1', sessionId: 's1', created: false }),
    uploadScreenshot: async () => ({ id: 'a1', path: '/x.png', filename: 'x.png', mimeType: 'image/png', size: 1 }),
    attachmentInput: (upload: { id: string }) => ({ type: 'attachment', attachment_id: upload.id }),
    close: () => {},
  } as unknown as PetAgentClient
}

async function makeChannel(): Promise<{ channel: SessionChannel; transport: ScriptedRpcTransport }> {
  const transport = makeTransport()
  const channel = new SessionChannel(makeClient(transport), { sessionId: 's1', projectId: 'p1' })
  await channel.open()
  return { channel, transport }
}

// ---------------------------------------------------------------------------
// 1. 通道行为：审批走共享映射，不再有第二套字符串匹配。
// ---------------------------------------------------------------------------
describe('SessionChannel 复用主界面审批控制器', () => {
  const cases: Array<{ id: string; want: string }> = [
    { id: 'approve', want: 'approve_once' },
    { id: 'trust', want: 'trust' },
    { id: 'decline', want: 'deny' },
    { id: 'option-skip', want: 'skip' },
  ]
  for (const item of cases) {
    it(`决策 ${item.id} 按主界面共享映射提交为 ${item.want}`, async () => {
      const { channel, transport } = await makeChannel()
      const payload = { partId: 'interaction:req-1', option: { id: item.id }, response: '' } as unknown as CoreDecisionSelectionPayload
      const result = await channel.handleDecision(payload)
      expect(result).toBe('approval')
      expect(transport.paramsOf('approval/respond')).toEqual(expect.objectContaining({
        request_id: 'req-1',
        thread_id: 's1',
        decision: item.want,
      }))
    })
  }

  it('同一个请求重复提交被去重（第二次 ignored）', async () => {
    const { channel, transport } = await makeChannel()
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    transport.handlers.set('approval/respond', () => gate.then(() => ({ ok: true })))
    const payload = { partId: 'interaction:req-1', option: { id: 'approve' }, response: '' } as unknown as CoreDecisionSelectionPayload
    const first = channel.handleDecision(payload)
    const second = await channel.handleDecision(payload)
    expect(second).toBe('ignored')
    release()
    expect(await first).toBe('approval')
  })

  it('非审批的文本决策走正常发送（turn/start）', async () => {
    const { channel, transport } = await makeChannel()
    const payload = { partId: 'part-not-exist', option: {}, response: '好，就这样' } as unknown as CoreDecisionSelectionPayload
    const result = await channel.handleDecision(payload)
    expect(result).toBe('text')
    expect(transport.paramsOf('turn/start')).toEqual(expect.objectContaining({
      thread_id: 's1',
      input: [{ type: 'text', text: '好，就这样' }],
    }))
  })
})

// ---------------------------------------------------------------------------
// 2. 通道行为：分叉/回退与主界面走同一条线协议。
// ---------------------------------------------------------------------------
describe('SessionChannel 分叉与回退', () => {
  it('forkTurn 提交 session.fork 并返回新会话 id', async () => {
    const { channel, transport } = await makeChannel()
    const forked = await channel.forkTurn('turn-1')
    expect(forked).toBe('fork-9')
    expect(transport.paramsOf('session.fork')).toEqual(expect.objectContaining({
      session_id: 's1',
      turn_id: 'turn-1',
    }))
  })

  it('rollbackTurn 提交 session.rollback 并重新拉取会话快照', async () => {
    const { channel, transport } = await makeChannel()
    await channel.rollbackTurn('turn-1')
    expect(transport.paramsOf('session.rollback')).toEqual(expect.objectContaining({
      session_id: 's1',
      turn_id: 'turn-1',
    }))
    // 重建连接：回退后重新 initialize + 读取持久化线程（与主界面刷新一致）。
    expect(transport.methods().filter(method => method === 'initialize')).toHaveLength(2)
    expect(transport.methods().filter(method => method === 'thread/read')).toHaveLength(2)
  })
})

// ---------------------------------------------------------------------------
// 3. 卡片组件：引用主界面同款组件，不再自带一套。
// ---------------------------------------------------------------------------
describe('SessionCard 与主界面同源（源码契约）', () => {
  const source = () => readFileSync(resolve(uiRoot, 'pet/ui/SessionCard.vue'), 'utf8')
  const hostSource = () => readFileSync(resolve(uiRoot, 'pet/agent/host.ts'), 'utf8')

  it('卡片渲染用 ChatThread，不再自己循环 MessageView', () => {
    expect(source()).toContain("from '@/components/ChatThread.vue'")
    expect(source()).not.toContain("from '@/components/MessageView.vue'")
  })

  it('卡片输入区用主界面 ComposerBar + InlineFileComposer，不再有裸 textarea', () => {
    expect(source()).toContain("from '@/components/ComposerBar.vue'")
    expect(source()).toContain("from '@/components/InlineFileComposer.vue'")
    expect(source()).toContain("from '@/components/CoreSendStopButton.vue'")
    expect(source(), '不允许自建输入框').not.toMatch(/<textarea/)
  })

  it('卡片不再有手写审批映射', () => {
    const text = source()
    expect(text).not.toContain("includes('deny')")
    expect(text).not.toContain('resolveRequestId')
    expect(text).toContain('handleDecision')
  })

  it('通道装配共享投影控制器与共享审批控制器', () => {
    expect(hostSource()).toContain('useCoreWorkbenchProjectionController')
    expect(hostSource()).toContain('useCoreApprovalController')
    expect(hostSource()).not.toContain('selectCoreWorkbenchMessages(')
  })
})

// ---------------------------------------------------------------------------
// 5. 样式同源：覆盖层加载主界面设计令牌并跟随主题，卡片用主题令牌与玻璃原语。
// ---------------------------------------------------------------------------
describe('覆盖层样式与主界面同源', () => {
  const petEntry = () => readFileSync(resolve(uiRoot, '../../desktop/src/pet.ts'), 'utf8')

  it('覆盖层入口加载主界面设计令牌与玻璃原语', () => {
    const source = petEntry()
    expect(source).toContain('@/styles/variables.css')
    expect(source).toContain('@/styles/base.css')
    expect(source).toContain('@/styles/optical-glass.css')
  })

  it('覆盖层根组件应用主界面同一份主题偏好', () => {
    const surface = readFileSync(resolve(uiRoot, 'pet/ui/PetSurface.vue'), 'utf8')
    expect(surface).toContain('useOverlayTheme')
    const theme = readFileSync(resolve(uiRoot, 'pet/ui/overlayTheme.ts'), 'utf8')
    expect(theme).toContain('useCoreUiPreferences')
    expect(theme).toContain('themeToCSSVars')
    expect(theme).toContain('applyStoredPublishedTheme')
  })

  it('卡片外壳使用主题令牌，不再自带一套颜色', () => {
    const source = readFileSync(resolve(uiRoot, 'pet/ui/SessionCard.vue'), 'utf8')
    expect(source).toContain('--theme-main-text')
    expect(source).not.toContain('--pet-glass')
    expect(source, '表面材质由主题变量提供').not.toMatch(/backdrop-filter:\s*blur/)
    expect(source, '不再硬编码卡片底色').not.toContain('rgba(20, 22, 28')
  })

  // user:“先原状复刻”+(卡片窗口的聊天面板与主界面主内容面板同一组声明：
  // 主区域底色/图片层/玻璃滤镜/边框/文字色全部读主题变量。)
  it('卡片即窗口：独立入口、无原生边框、主面板配方', () => {
    const card = readFileSync(resolve(uiRoot, 'pet/ui/SessionCard.vue'), 'utf8')
    expect(card).toContain('background: var(--theme-main-background)')
    expect(card).toContain('backdrop-filter: var(--theme-main-glass-filter')
    expect(card).toContain('border: 1px solid var(--theme-main-border)')
    expect(card, '独立窗口模式：拖标题栏移动原生窗口').toContain('startDragging')
    const surface = readFileSync(resolve(uiRoot, 'pet/ui/PetSurface.vue'), 'utf8')
    expect(surface).not.toContain('PetCards')
    const windowPage = readFileSync(resolve(uiRoot, 'pet/ui/PingCardWindow.vue'), 'utf8')
    expect(windowPage).toContain('SessionCard')
    expect(windowPage).toContain('standalone')
    expect(windowPage).toContain('PetAgentHost')
    const entry = readFileSync(resolve(uiRoot, '../../desktop/src/pingCard.ts'), 'utf8')
    expect(entry).toContain('PingCardWindow')
    expect(entry, '卡片页加载主界面全局样式（输入栏/消息区）').toContain('@/styles/layout.css')
    const cardHtml = readFileSync(resolve(uiRoot, '../../desktop/card.html'), 'utf8')
    expect(cardHtml).toContain('pingCard.ts')
    const rust = readFileSync(resolve(uiRoot, '../../desktop/src-tauri/src/pet/cards.rs'), 'utf8')
    // user:“低透玻璃的磨砂没有做出来”“关键是模糊”+(卡片窗口与主窗口同一材质：
    // 原生 Acrylic 负责模糊桌面。)
    expect(rust).toContain('Effect::Acrylic')
    // user:“不要再自作聪明了”“圆不圆角你就看 Sunday 本身是什么样”+(卡片窗口
    // 照搬主窗口建窗参数：无边框、透明、透明背景色、系统阴影、创建即可见；
    // 不再手动清 Win32 样式、不强制重绘、不自定义窗口圆角。)
    expect(rust).toContain('.decorations(false)')
    expect(rust).toContain('.transparent(true)')
    expect(rust).toContain('.shadow(true)')
    expect(rust).toContain('background_color')
    expect(rust).not.toContain('visible(false)')
    expect(rust).not.toContain('strip_native_frame')
    expect(rust).not.toContain('NCRENDERING')
    expect(rust).not.toContain('RedrawWindow')
    expect(rust).not.toContain('CreateRoundRectRgn')
    expect(rust).toContain('WebviewWindowBuilder')
    expect(rust).toContain('place_overlay')
    const petMod = readFileSync(resolve(uiRoot, '../../desktop/src-tauri/src/pet/mod.rs'), 'utf8')
    expect(petMod).toContain('pet_open_ping_card')
    expect(petMod).toContain('pet_close_ping_card')
    // user:“环出现了，但是我把它选中到对话之后，没有任何的窗口打开”+
    // (卡片命令必须 async：同步命令在 WebView2 IPC 线程里建/关窗口会死锁。)
    expect(petMod).toMatch(/pub async fn pet_open_ping_card/)
    expect(petMod).toMatch(/pub async fn pet_show_ping_card/)
    expect(petMod).toMatch(/pub async fn pet_close_ping_card/)
    const pingSurface = readFileSync(resolve(uiRoot, 'pet/ui/PingSurface.vue'), 'utf8')
    // user:“ping完之后用一个合适的大小打开Sunday本体…这样最大程度复用”+
    // (Ping 不再管理卡片窗口：发送/对话都直接唤起主窗口。)
    const pingRuntime = readFileSync(resolve(uiRoot, 'pet/ping/usePingRuntime.ts'), 'utf8')
    expect(pingRuntime).toContain('openMainSession')
    expect(pingSurface).not.toContain('openPingCard')
    expect(pingSurface).not.toContain('closePingCard')
  })

  // user:“你看看 ping 环 要不也自己做窗口？”+(Ping 有自己的全屏覆盖层窗口：
  // 环/标记/标注/选择器 + 运行时 + 热键都在那里；桌宠运行时不再创建 Ping。)
  it('Ping 环独立成窗口，桌宠不再持有 Ping 运行时', () => {
    const surface = readFileSync(resolve(uiRoot, 'pet/ui/PingSurface.vue'), 'utf8')
    expect(surface).toContain('createPingRuntime')
    expect(surface).toContain('PingRing')
    expect(surface).toContain('PingMarkerFx')
    expect(surface).toContain('PingAnnotator')
    expect(surface).toContain('attachNativeEvents')
    expect(surface).toContain('showPingOverlay')
    // user:“通过 ping 环切到目标会话那一项，是不是还依赖着桌宠的那个窗口了？”
    // +(选择器在 Ping 窗口内打开：命中矩形必须等面板渲染完再上报，否则面板
    //  看得见却点不到（窗口在面板区域仍是穿透）。)
    expect(surface).toContain('nextTick')
    expect(surface).toContain("flush: 'post'")
    expect(surface).toContain('setPingInteractiveRects')
    const pet = readFileSync(resolve(uiRoot, 'pet/ui/usePetRuntime.ts'), 'utf8')
    expect(pet, '桌宠不再创建 Ping 运行时').not.toContain('createPingRuntime(')
    expect(pet, '桌宠不再转发 Ping 光标').not.toContain('onCursorMoved')
    const petSurface = readFileSync(resolve(uiRoot, 'pet/ui/PetSurface.vue'), 'utf8')
    expect(petSurface).not.toContain('PingRing')
    const entry = readFileSync(resolve(uiRoot, '../../desktop/src/ping.ts'), 'utf8')
    expect(entry).toContain('PingSurface')
    const pingHtml = readFileSync(resolve(uiRoot, '../../desktop/ping.html'), 'utf8')
    expect(pingHtml).toContain('ping.ts')
    const rust = readFileSync(resolve(uiRoot, '../../desktop/src-tauri/src/pet/mod.rs'), 'utf8')
    expect(rust).toContain('PING_OVERLAY_LABEL')
    expect(rust).toContain('pet_ping_overlay_show')
    expect(rust).toContain('pet_ping_set_interactive_rects')
  })

  // user:“输入框的位置没对上”+(嵌入式输入栏由托管方负责和卡片内容对齐：
  // 与辅助对话同一套外边距/宽度规则，输入卡不再贴住卡片边缘。)
  it('输入栏按辅助对话同一套托管规则与卡片内容对齐', () => {
    const source = readFileSync(resolve(uiRoot, 'pet/ui/SessionCard.vue'), 'utf8')
    expect(source).toContain('.pet-card > .pet-card__composer')
    expect(source).toContain('margin: var(--space-2) var(--space-3) var(--space-3)')
    expect(source).toMatch(/width:\s*auto;/)
  })
})

describe('overlay 主题跟随', () => {
  const PREFERENCES_KEY = 'lamtools.core.ui.preferences'

  // 主界面持久化的是完整偏好（light/dark 两套主题）；这里按同一结构播种。
  async function seedPreferences(themeMode: 'dark' | 'light') {
    const { SUNDAY_DARK_THEME, SUNDAY_LIGHT_THEME } = await import('../src/helpers/theme.ts')
    localStorage.setItem(PREFERENCES_KEY, JSON.stringify({
      themeMode,
      lightTheme: { ...SUNDAY_LIGHT_THEME },
      darkTheme: { ...SUNDAY_DARK_THEME },
    }))
  }

  async function mountOverlayTheme() {
    const { useOverlayTheme } = await import('../src/pet/ui/overlayTheme.ts')
    const Host = { setup() { useOverlayTheme(); return () => null } }
    return mount(Host)
  }

  it('按主界面存储的主题模式把 --theme-* 变量写进覆盖层根节点', async () => {
    await seedPreferences('dark')
    const wrapper = await mountOverlayTheme()
    try {
      await flushPromises()
      const darkText = document.documentElement.style.getPropertyValue('--theme-main-text')
      expect(darkText).toBeTruthy()
      expect(document.documentElement.style.getPropertyValue('--theme-composer-background')).toBeTruthy()
    } finally {
      wrapper.unmount()
    }
  })

  it('主窗口换主题（storage 事件）后覆盖层即时跟随', async () => {
    await seedPreferences('dark')
    const wrapper = await mountOverlayTheme()
    try {
      await flushPromises()
      const darkValue = document.documentElement.style.getPropertyValue('--theme-main-background')
      await seedPreferences('light')
      window.dispatchEvent(new StorageEvent('storage', { key: PREFERENCES_KEY, newValue: localStorage.getItem(PREFERENCES_KEY) }))
      await flushPromises()
      const lightValue = document.documentElement.style.getPropertyValue('--theme-main-background')
      expect(lightValue).toBeTruthy()
      expect(lightValue).not.toBe(darkValue)
    } finally {
      wrapper.unmount()
    }
  })
})

// ---------------------------------------------------------------------------
// 4. 卡片挂载：真实通道 + 假传输，验证整条渲染与决策链路。
// ---------------------------------------------------------------------------
describe('SessionCard 挂载验收', () => {
  function makePing(channel: SessionChannel, client: PetAgentClient): { ping: PingRuntime; card: CardState } {
    const card: CardState = {
      sessionId: 's1', projectId: 'p1', pinned: false,
      containerX: 100, containerY: 100, cardX: 124, cardY: 124,
      title: '测试会话', unread: 0, draft: '', pendingAttachments: [],
    }
    const ping = {
      cards: new Map([[card.sessionId, card]]),
      host: ref({ get: (id: string) => id === card.sessionId ? channel : undefined }),
      client: ref(client),
      overlay: { x: 0, y: 0, width: 1920, height: 1080 },
      activeCardSession: ref('s1'),
      moveCard: () => {},
      pinCard: () => {},
      unpinCard: () => {},
      closeCard: () => {},
      pending: { attach: null },
    } as unknown as PingRuntime
    return { ping, card }
  }

  it('渲染主界面线程与主界面输入区，消息操作开启', async () => {
    const { channel, transport } = await makeChannel()
    const client = makeClient(transport)
    const { ping, card } = makePing(channel, client)
    const wrapper = mount(SessionCard, { props: { ping, card } })
    try {
      expect(wrapper.find('[data-region="ping-card"]').exists()).toBe(true)
      expect(wrapper.find('[data-ui-id="chat.thread"]').exists()).toBe(true)
      expect(wrapper.find('form.floating-composer').exists()).toBe(true)
      expect(wrapper.find('.core-send-stop-button').exists()).toBe(true)
      const thread = wrapper.findComponent(ChatThread)
      expect(thread.props('messageActions')).toBe(true)
      expect(thread.props('projectId')).toBe('p1')
    } finally {
      wrapper.unmount()
    }
  })

  it('卡片里的审批按钮经 ChatThread 到共享控制器提交', async () => {
    const { channel, transport } = await makeChannel()
    const client = makeClient(transport)
    const { ping, card } = makePing(channel, client)
    const wrapper = mount(SessionCard, { props: { ping, card } })
    try {
      const thread = wrapper.findComponent(ChatThread)
      thread.vm.$emit('decision-select', { partId: 'interaction:req-2', option: { id: 'approve' }, response: '' })
      await flushPromises()
      expect(transport.paramsOf('approval/respond')).toEqual(expect.objectContaining({
        request_id: 'req-2',
        decision: 'approve_once',
      }))
    } finally {
      wrapper.unmount()
    }
  })

  it('过程展开/收起走共享投影状态', async () => {
    const { channel, transport } = await makeChannel()
    const client = makeClient(transport)
    const { ping, card } = makePing(channel, client)
    const wrapper = mount(SessionCard, { props: { ping, card } })
    try {
      channel.toggleProcess('message-1')
      await flushPromises()
      expect(channel.processExpandedIds().value.has('message-1')).toBe(true)
      channel.toggleProcess('message-1')
      expect(channel.processExpandedIds().value.has('message-1')).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })
})
