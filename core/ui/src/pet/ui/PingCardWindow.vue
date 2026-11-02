<script setup lang="ts">
/**
 * Ping 会话卡片窗口（卡片即窗口）。
 *
 * user:“卡片即窗口，把 ping 和桌宠拆分开”
 * +(每张卡片一个独立窗口：窗口自带原生 Acrylic 磨砂，页面只负责卡片内容；
 *   窗口自己建一条真实会话通道（消息/流式/审批/发送），不依赖桌宠覆盖层。)
 */
import { computed, onMounted, reactive, ref } from 'vue'
import SessionCard from './SessionCard.vue'
import { useOverlayTheme } from './overlayTheme.ts'
import { createPetAgentClient, type PetAgentClient } from '../agent/client.ts'
import { PetAgentHost, SessionChannel } from '../agent/host.ts'
import { useCoreExecutionControlsState } from '@/composables/useCoreExecutionControlsState.ts'
import type { CoreExecutionModelSource, CoreExecutionProviderSource, CoreModelCatalogView } from '@/composer/execution.ts'
import * as bridge from '../bridge.ts'
import type { CardState, PingRuntime } from '../ping/usePingRuntime.ts'

// 与主界面/覆盖层同一份主题（同一 localStorage 键）。
useOverlayTheme()

const params = new URLSearchParams(window.location.search)
const cardId = params.get('card') || params.get('session') || 'card'
const sessionId = params.get('session') || cardId
const projectId = params.get('project') || null
const title = params.get('title') || sessionId.slice(0, 8)

const client = ref<PetAgentClient | null>(null)
const agentHost = ref<PetAgentHost | null>(null)

// 输入参数组的数据源（与主界面同一套控件与状态实现）。
const models = ref<CoreExecutionModelSource[]>([])
const providers = ref<CoreExecutionProviderSource[]>([])
const catalogView = ref<CoreModelCatalogView>('provider')
const defaultModel = computed(() => {
  const rows = models.value as Array<CoreExecutionModelSource & { is_default?: boolean }>
  return rows.find(row => row.is_default) || rows[0] || null
})
const execution = useCoreExecutionControlsState({
  models,
  providers,
  catalogView,
  defaultModel,
  storage: typeof localStorage === 'undefined' ? null : localStorage,
})

const card = reactive<CardState>({
  sessionId,
  projectId,
  pinned: true,
  containerX: 0,
  containerY: 0,
  cardX: 0,
  cardY: 0,
  title,
  unread: 0,
  draft: '',
  pendingAttachments: [],
})

const cards = reactive(new Map<string, CardState>([[sessionId, card]]))
const activeCardSession = ref<string | null>(sessionId)
const overlayBounds = { x: 0, y: 0, width: 0, height: 0 }

function scale(): number {
  return window.devicePixelRatio || 1
}

/** 分叉后在新窗口里打开分叉会话（卡片即窗口的等价“跳转”）。 */
function openForkedCard(project: string | null, session: string): CardState {
  const ratio = scale()
  void bridge.openPingCard({
    cardId: session,
    sessionId: session,
    projectId: project,
    title: session.slice(0, 8),
    rect: [
      Math.round(80 * ratio),
      Math.round(80 * ratio),
      Math.round(380 * ratio),
      Math.round(460 * ratio),
    ],
  }).catch(() => undefined)
  return {
    sessionId: session,
    projectId: project,
    pinned: true,
    containerX: 0,
    containerY: 0,
    cardX: 0,
    cardY: 0,
    title: session.slice(0, 8),
    unread: 0,
    draft: '',
    pendingAttachments: [],
  }
}

// SessionCard 需要的 Ping 运行时表面：独立窗口里只有“这一张卡”，
// 位置由窗口本身负责（原生拖动）；钉住 = 窗口置顶开关。
const ping = {
  config: { enabled: true, ping: {} },
  overlay: overlayBounds,
  cards,
  activeCardSession,
  host: computed(() => agentHost.value),
  client: computed(() => client.value),
  pending: reactive({ attach: null }),
  ensureCard: openForkedCard,
  moveCard: () => {},
  pinCard: () => setPinned(true),
  unpinCard: () => setPinned(false),
  closeCard: () => { void bridge.closePingCard(cardId).catch(() => undefined) },
} as unknown as PingRuntime

/** 钉子：独立卡片窗口的置顶开关（创建时窗口就是置顶的）。 */
function setPinned(pinned: boolean): void {
  card.pinned = pinned
  void (async () => {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window')
      await getCurrentWindow().setAlwaysOnTop(pinned)
    } catch {
      /* 非 Tauri 预览环境忽略 */
    }
  })()
}

async function waitForApiBase(timeoutMs = 60_000): Promise<string> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      return await bridge.apiBase()
    } catch (error) {
      if (Date.now() > deadline) throw error
      await new Promise(resolve => setTimeout(resolve, 500))
    }
  }
}

onMounted(() => {
  void (async () => {
    try {
      const base = await waitForApiBase()
      const created = createPetAgentClient(base)
      client.value = created
      const host = new PetAgentHost(created)
      agentHost.value = host
      // 窗口自己的会话通道：流式、审批、发送都走真实后端。
      const channel = host.channel(projectId, sessionId)
      // user:“为什么会话标题是work flow”+(URL 里的标题只是会话 id 前 8 位的临时值，
      // 打开后立即用项目会话列表里的真实标题替换。)
      void resolveCardTitle(created)
      // user:“输入框缺东西”+(输入参数组复用主界面：模型/供应商目录走同一批
      // app-server 配置接口，控件与主界面完全相同。)
      void loadExecutionCatalog(channel)
    } catch (cause) {
      console.error('[ping-card] boot failed', cause)
    } finally {
      // 首帧合成后再显示窗口，避免白闪。
      requestAnimationFrame(() => requestAnimationFrame(() => {
        void bridge.showPingCard(cardId).catch(() => undefined)
      }))
    }
  })()
})

// -------------------------------------------------------------------------
// 输入参数组（模型/思考/模式/权限）：与主界面同一套共享状态与控件
// -------------------------------------------------------------------------

/** 会话真实标题：会话列表里的 title；查不到时保留临时标题。 */
async function resolveCardTitle(agent: PetAgentClient): Promise<void> {
  if (!projectId) return
  try {
    const sessions = await agent.listSessions(projectId)
    const matched = sessions.find(session => session.id === sessionId)
    const resolved = matched?.title?.trim()
    if (resolved && resolved !== sessionId) card.title = resolved
  } catch {
    /* 标题解析失败不影响会话本身。 */
  }
}

async function loadExecutionCatalog(channel: SessionChannel): Promise<void> {
  try {
    const [providersResponse, modelsResponse] = await Promise.all([
      channel.requestRpc('config.providers.list').catch(() => ({})),
      channel.requestRpc('config.models.list').catch(() => ({})),
    ])
    const providerRows = (providersResponse as { providers?: unknown }).providers
    const modelRows = (modelsResponse as { models?: unknown }).models
    if (Array.isArray(providerRows)) providers.value = providerRows as CoreExecutionProviderSource[]
    if (Array.isArray(modelRows)) models.value = modelRows as CoreExecutionModelSource[]
  } catch (cause) {
    console.error('[ping-card] load execution catalog failed', cause)
  }
}
</script>

<template>
  <SessionCard :ping="ping" :card="card" standalone :execution="execution" />
</template>
