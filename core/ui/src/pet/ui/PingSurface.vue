<script setup lang="ts">
/**
 * Ping 独立覆盖层根组件。
 *
 * user:“你看看 ping 环 要不也自己做窗口？”
 * +(环、标记动画、框选标注、会话选择器有了自己的全屏透明窗口；Ping 运行时、
 *   全局热键、会话路由、卡片窗口全部归这里。桌宠覆盖层关掉/禁用/崩溃都不影响
 *   Ping；桌宠那边只保留角色、气泡和设置。)
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import PingRing from './PingRing.vue'
import PingMarkerFx from './PingMarkerFx.vue'
import SessionPicker, { type SessionPickerView } from './SessionPicker.vue'
import { createPingRuntime } from '../ping/usePingRuntime.ts'
import { ringSectors } from '../ping/ringModel.ts'
import { defaultConfig, parseConfigText, PET_CONFIG_VERSION, type PetConfigV1 } from '../config.ts'
import { patchPetConfig } from '../configFile.ts'
import { createPetAgentClient, type PetAgentClient } from '../agent/client.ts'
import { PetAgentHost } from '../agent/host.ts'
import * as bridge from '../bridge.ts'
import { useOverlayTheme } from './overlayTheme.ts'

// 与主界面/桌宠同一份主题。
useOverlayTheme()

const config = reactive<PetConfigV1>(defaultConfig())
const overlay = reactive({ x: 0, y: 0, width: 0, height: 0, scale: 1 })
const monitors = ref<Awaited<ReturnType<typeof bridge.listMonitors>>>([])
const cursor = reactive({ x: 0, y: 0, inside: false })
const agentClient = shallowRef<PetAgentClient | null>(null)
const agentHost = shallowRef<PetAgentHost | null>(null)

const picker = reactive<SessionPickerView>({
  open: false,
  mode: 'ping',
  petId: '',
  projects: [],
  sessions: [],
  projectId: null,
  targetSessionId: null,
  targetProjectId: null,
  loading: false,
})

// -------------------------------------------------------------------------
// Ping 运行时（与桌宠运行时同一套实现，只是运行在独立窗口里）
// -------------------------------------------------------------------------

const ping = createPingRuntime({
  config,
  overlay,
  monitors: () => monitors.value,
  cursor,
  getHost: () => agentHost.value,
  getClient: () => agentClient.value,
  save: scheduleSave,
  report: (scope, error) => console.error(`[ping] ${scope}`, error),
  notify: input => { void emitToApp('pet://ping/notify', input) },
  openSessionPicker: (projectId?: string) => { void openPicker(projectId) },
  // user:“重新设计与实现 Ping 的框选工具”+(截图/框选交给独立窗口；
  // 覆盖层只负责把入口点开，不再整屏吃鼠标。)
  openCapture: () => bridge.openPingCapture().then(() => undefined),
  // 三级会话轮盘的数据源（项目 → 项目内最近会话）。
  listProjects: async () => {
    const client = agentClient.value
    if (!client) return []
    return (await client.listProjects()).map(project => ({ id: project.id, name: project.name }))
  },
  listSessions: async (projectId: string) => {
    const client = agentClient.value
    if (!client) return []
    return (await client.listSessions(projectId))
      .filter(session => !session.internal)
      .map(session => ({ id: session.id, title: session.title, updatedAt: session.updatedAt }))
  },
  // 桌宠侧动作（设置/导入/显隐宠物/刷新地形…）由桌宠窗口执行；它没开时静默忽略。
  customActions: {
    openSettings: () => { void emitToApp('pet://ping/action', 'settings') },
    openImporter: () => emitToApp('pet://ping/action', 'importer'),
    togglePets: () => { void emitToApp('pet://ping/action', 'toggle-pets') },
    refreshTerrain: () => emitToApp('pet://ping/action', 'refresh-terrain'),
    toggleTerrainLines: () => { void emitToApp('pet://ping/action', 'toggle-terrain-lines') },
    hideOverlay: () => emitToApp('pet://ping/action', 'hide-overlay'),
  },
})

async function emitToApp(event: string, payload?: unknown): Promise<void> {
  try {
    const { emit } = await import('@tauri-apps/api/event')
    await emit(event, payload)
  } catch {
    /* 宿主事件失败不阻塞 Ping */
  }
}

// -------------------------------------------------------------------------
// Ping 完成后的去向：打开 Sunday 本体（会话切换由主窗口自己处理）
// -------------------------------------------------------------------------
// user:“ping完之后用一个合适的大小打开Sunday本体…这样最大程度复用”+
// (Ping 页不再管理卡片窗口：发送/对话都调用主窗口，圆角和材质全部复用本体。)

/** 本页注册的事件监听，卸载/热更新时统一摘掉。 */
const eventOffs: Array<() => void> = []

async function subscribeEvents(): Promise<void> {
  const { listen } = await import('@tauri-apps/api/event')
  // user:“为什么会一瞬间给我弹出来这么多东西”+(热更新会重新挂载页面；
  // 事件监听必须随时可摘掉，否则一次快捷键会被重复执行多次。)
  eventOffs.push(await listen<{ x: number; y: number; inside: boolean }>('pet://cursor', ({ payload }) => {
    cursor.x = payload.x
    cursor.y = payload.y
    cursor.inside = payload.inside
    ping.onCursorMoved(payload.x, payload.y)
    // 只在有可点 UI 时才量矩形（隐藏时窗口整体穿透，不需要命中区）。
    if (overlayActive.value) void reportHitRects()
  }))
  // 主界面设置/桌宠面板改了同一份 config.json：重读后立即生效。
  eventOffs.push(await listen('pet://config-changed', () => { void reloadConfig() }))
  // CLI/自动化入口：直接执行某个扇区（不模拟键鼠）。
  // user:“你为什么不CLI先行用CLI直接执行 ping 环内的操作”
  eventOffs.push(await listen<string>('pet://ping/test-commit', ({ payload }) => {
    const sector = ringSectors(config.ping.sectors, null).find(item => item.id === payload)
    if (!sector) {
      console.warn('[ping] test-commit unknown sector', payload)
      return
    }
    console.log('[ping] test-commit', sector.id, sector.kind)
    void ping.executeSector(sector, { x: cursor.x, y: cursor.y })
  }))
}

/** 摘掉本页注册的所有事件监听（卸载或热更新时调用）。 */
function teardownEvents(): void {
  for (const off of eventOffs.splice(0)) {
    try { off() } catch { /* 已失效的监听忽略 */ }
  }
  ping.detachNativeEvents()
}

if (import.meta.hot) {
  // 热更新不会走 onBeforeUnmount：显式清理，避免监听越叠越多。
  import.meta.hot.dispose(() => { teardownEvents() })
}

// -------------------------------------------------------------------------
// 覆盖层窗口常显：环/标注出现即可见，不再按需隐藏
// （隐藏窗口会被浏览器节流，热键/页面响应都会变慢）。
// -------------------------------------------------------------------------

const overlayActive = computed(() => (
  ping.ring.visible
  || ping.markerFx.visible
  || picker.open
))

watch(overlayActive, active => {
  if (!active) return
  void bridge.showPingOverlay().catch(error => {
    console.error('[ping] show overlay failed', error)
  })
})

// -------------------------------------------------------------------------
// 命中矩形（选择器等可点 UI）：只在有变化时上报
// -------------------------------------------------------------------------

let lastReportedRects = ''
async function reportHitRects(): Promise<void> {
  // 用覆盖层的“物理宽 / 页面宽”换算，而不是页面自报的 devicePixelRatio：
  // 某些缩放组合下页面 dpr 与真实缩放不一致，命中矩形会整体偏移。
  const ratio = overlay.width / Math.max(1, window.innerWidth)
  const rects: number[][] = []
  for (const el of document.querySelectorAll('[data-pet-hit]')) {
    const box = el.getBoundingClientRect()
    if (box.width < 4 || box.height < 4) continue
    rects.push([
      Math.round(overlay.x + box.left * ratio),
      Math.round(overlay.y + box.top * ratio),
      Math.round(box.width * ratio),
      Math.round(box.height * ratio),
    ])
  }
  const key = rects.map(rect => rect.join(',')).join('|')
  if (key === lastReportedRects) return
  lastReportedRects = key
  void bridge.setPingInteractiveRects(rects).catch(() => undefined)
}

let rectRetryTimer = 0
function scheduleReportHitRects(): void {
  // 面板刚打开时 DOM 还没渲染：必须等本帧渲染完再量矩形，否则窗口在面板区域
  // 仍是穿透状态，面板看得见却点不到。稍后再量一次兜住布局抖动。
  void (async () => {
    await nextTick()
    await reportHitRects()
  })()
  if (rectRetryTimer) window.clearTimeout(rectRetryTimer)
  rectRetryTimer = window.setTimeout(() => {
    rectRetryTimer = 0
    void reportHitRects()
  }, 200)
}

watch([() => picker.open, overlayActive], scheduleReportHitRects, { flush: 'post' })

// -------------------------------------------------------------------------
// 会话选择器（Ping 目标）
// -------------------------------------------------------------------------

async function openPicker(preselectProjectId?: string): Promise<void> {
  picker.open = true
  picker.loading = true
  picker.error = ''
  picker.targetSessionId = config.ping.target?.sessionId || null
  picker.targetProjectId = config.ping.target?.projectId || null
  try {
    const client = agentClient.value
    if (!client) throw new Error('会话客户端未就绪')
    const projects = await client.listProjects()
    picker.projects = projects.map(project => ({ id: project.id, name: project.name }))
    // 指定项目（轮盘选“更多…”）优先；否则默认展开当前目标所在项目，少点一次。
    const initial = preselectProjectId || picker.targetProjectId || projects[0]?.id
    if (initial) {
      picker.loading = false
      await loadSessions(initial)
    }
  } catch (error) {
    picker.error = error instanceof Error ? error.message : String(error)
  } finally {
    picker.loading = false
  }
}

async function loadSessions(projectId: string): Promise<void> {
  picker.projectId = projectId
  picker.loading = true
  picker.error = ''
  try {
    const client = agentClient.value
    if (!client) throw new Error('会话客户端未就绪')
    const sessions = await client.listSessions(projectId)
    // 插件/内部编排会话不能当 Ping 目标。
    picker.sessions = sessions
      .filter(session => !session.internal)
      .map(session => ({ id: session.id, title: session.title }))
  } catch (error) {
    picker.error = error instanceof Error ? error.message : String(error)
  } finally {
    picker.loading = false
  }
}

function chooseSession(sessionId: string): void {
  const projectId = picker.projectId
  if (!projectId) return
  picker.open = false
  ping.applyPickedTarget(projectId, sessionId)
}

function closePicker(): void {
  picker.open = false
}

// -------------------------------------------------------------------------
// 配置读取与保存（与桌宠共用同一个配置文件；只改 ping 相关字段）
// -------------------------------------------------------------------------

let saveTimer = 0
function scheduleSave(): void {
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => { void persistConfig() }, 400)
}

async function persistConfig(): Promise<void> {
  try {
    // 只提交 Ping 拥有的两段；Rust 在同一把锁里合并，不会覆盖桌宠/主界面刚写的字段。
    await patchPetConfig({
      version: PET_CONFIG_VERSION,
      ping: config.ping,
      bindings: { ping: { ...(agentHost.value?.bindings.ping || config.bindings.ping) } },
    })
  } catch (error) {
    console.error('[ping] save config failed', error)
  }
}

async function reloadConfig(): Promise<void> {
  try {
    const text = await bridge.readConfigText()
    if (!text) return
    const parsed = parseConfigText(text)
    Object.assign(config, parsed.config)
    await ping.applyHotkey()
  } catch (error) {
    console.error('[ping] reload config failed', error)
  }
}

// -------------------------------------------------------------------------
// 启动
// -------------------------------------------------------------------------

function waitForApiBase(timeoutMs = 60_000): Promise<string> {
  const deadline = Date.now() + timeoutMs
  const loop = async (): Promise<string> => {
    try {
      return await bridge.apiBase()
    } catch (error) {
      if (Date.now() > deadline) throw error
      await new Promise(resolve => window.setTimeout(resolve, 500))
      return await loop()
    }
  }
  return loop()
}

// 框选/轮盘的兜底退出：即使标注组件渲染异常，Esc 也要能把输入模式恢复。
function onSelectionEscape(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (picker.open) {
    event.preventDefault()
    picker.open = false
    return
  }
  if (ping.ring.visible) {
    event.preventDefault()
    ping.cancelRing()
  }
}

onMounted(() => {
  console.log('[ping] surface mounted')
  window.addEventListener('keydown', onSelectionEscape)
  void (async () => {
    try {
      // 窗口由宿主在启动时建好（隐藏）；这里拿到虚拟桌面边界并读取配置。
      const bounds = await bridge.openPingOverlay()
      console.log('[ping] overlay bounds', JSON.stringify(bounds))
      Object.assign(overlay, bounds)
      monitors.value = await bridge.listMonitors()
      const text = await bridge.readConfigText()
      if (text) Object.assign(config, parseConfigText(text).config)
      console.log('[ping] config loaded hotkey=', config.ping.hotkey)
      await ping.applyHotkey()
      console.log('[ping] hotkey applied')
      ping.attachNativeEvents()
      await subscribeEvents()
      console.log('[ping] events attached')
      const base = await waitForApiBase()
      console.log('[ping] api base', base)
      const client = createPetAgentClient(base)
      agentClient.value = client
      const host = new PetAgentHost(client, config.bindings, bindings => {
        config.bindings = bindings
        scheduleSave()
      })
      agentHost.value = host
      console.log('[ping] agent host ready')
    } catch (error) {
      console.error('[ping] boot failed', error)
    }
  })()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onSelectionEscape)
  teardownEvents()
  if (rectRetryTimer) window.clearTimeout(rectRetryTimer)
  if (saveTimer) window.clearTimeout(saveTimer)
  void bridge.hidePingOverlay().catch(() => undefined)
})
</script>

<template>
  <div class="ping-surface" data-region="ping-surface">
    <PingRing :ping="ping" />
    <PingMarkerFx :ping="ping" />
    <SessionPicker
      :picker="picker"
      :load-sessions="loadSessions"
      :choose-session="chooseSession"
      :close="closePicker"
    />
  </div>
</template>

<style scoped>
.ping-surface {
  position: fixed;
  inset: 0;
  pointer-events: none;
}

.ping-surface > :deep(.picker) {
  pointer-events: auto;
}
</style>
