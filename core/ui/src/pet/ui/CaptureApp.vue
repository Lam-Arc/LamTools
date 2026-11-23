<script setup lang="ts">
/**
 * 独立截图窗口的根组件：加载静态截图、维持心跳、负责发送与退出。
 *
 * user:“任何步骤按 Esc 都可以安全退出”+
 * (Esc/取消/关闭/发送完成都走同一个 close 命令；窗口销毁后宿主状态一起清空。
 *  页面每秒发一次心跳，宿主看门狗据此判断页面是否还活着。)
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import CaptureEditor, { type CaptureSelectionMeta } from './CaptureEditor.vue'
import { regionToFrame } from '../capture/geometry.ts'
import type { CapturedFrame } from '../bridge.ts'
import * as bridge from '../bridge.ts'
import { defaultConfig, parseConfigText } from '../config.ts'
import { createPetAgentClient } from '../agent/client.ts'
import { PetAgentHost } from '../agent/host.ts'
import { createDirectTransport, type DirectTransport } from '@/transport/directTransport.ts'
import { createTranslator, type TranslateInput, type TranslateOutcome } from '../translate/client.ts'

const props = defineProps<{
  frame: CapturedFrame | null
  bootError: string
  /** 标注层圈选带过来的屏幕区域，用来预置框选。 */
  presetRegion?: [number, number, number, number] | null
}>()

const busy = ref(false)
// 标注层圈选 → 截图内像素；无效或没带选区时为 null，保持 Ping 原来的空框选。
const initialRegion = computed(() => (
  props.frame && props.presetRegion ? regionToFrame(props.presetRegion, props.frame) : null
))
const error = ref(props.bootError)
let heartbeat = 0
let generation = 0
let activeClient: ReturnType<typeof createPetAgentClient> | null = null
let closing = false

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.preventDefault()
  void cancel()
}

async function cancel(): Promise<void> {
  // user:“任何步骤按 Esc 都可以安全退出”+(关闭时使进行中的发送失效并停止客户端)。
  if (closing) return
  closing = true
  generation++
  activeClient?.close()
  activeClient = null
  busy.value = false
  try {
    await bridge.closePingCapture()
  } catch (cause) {
    console.error('[capture] close failed', cause)
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    closing = false
  }
}

async function send(payload: { blob: Blob; text: string; meta: CaptureSelectionMeta }): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  const run = ++generation
  let client: ReturnType<typeof createPetAgentClient> | undefined
  // user:“确保视觉、功能和交互不退化”+(准备阶段失败也显示错误并解除忙碌，允许重试或退出)。
  try {
    const configText = await bridge.readConfigText().catch(() => null)
    if (run !== generation) return
    const config = configText ? parseConfigText(configText).config : defaultConfig()
    const base = await bridge.apiBase()
    if (run !== generation) return
    client = createPetAgentClient(base)
    activeClient = client
    const host = new PetAgentHost(client, config.bindings)
    const target = await host.pingTarget()
    if (run !== generation) return
    const channel = host.channel(target.projectId || null, target.sessionId)
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    const upload = await client.uploadScreenshot(
      channel.sessionId,
      channel.projectId,
      payload.blob,
      `ping-select-${stamp}.png`,
    )
    if (run !== generation) return
    // user:“ping的所有东西都是按引导进去的，不是按排队进去的”+
    // (发送走与 Ping 环相同的通道：活动回合里是引导，不排队。)
    const result = await channel.send(payload.text, [client.attachmentInput(upload)])
    if (run !== generation) return
    if (result.status === 'ignored') {
      throw new Error(result.message || 'Ping 消息未能送达目标会话')
    }
    console.log('[capture] sent', JSON.stringify(payload.meta))
    await bridge.openMainSession(target.projectId || null, target.sessionId)
    if (run !== generation) return
    await bridge.closePingCapture()
  } catch (cause) {
    if (run === generation) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      busy.value = false
    }
  } finally {
    if (activeClient === client) { client?.close(); activeClient = null }
  }
}

/**
 * 屏幕翻译：复用直调（direct.*）这条不进 Agent Loop 的直路。
 *
 * user:“用现有模型直调通道…不要接第三方翻译 API”+(截图窗口已经握着同一套
 * DirectTransport；这里只把 JSON-RPC 包成编辑器要的翻译函数，挑模型、发起与
 * 轮询都在 translate/client.ts，窗口自己不碰模型细节)。
 */
let translateTransport: DirectTransport | null = null

async function translateScreen(input: TranslateInput): Promise<TranslateOutcome> {
  if (!translateTransport) {
    const base = await bridge.apiBase()
    translateTransport = createDirectTransport({ apiBase: `${base}/api/core` })
  }
  const transport = translateTransport
  const translate = createTranslator((method, params) =>
    transport.request<Record<string, unknown>>({ kind: 'rpc', method, params }))
  return await translate(input)
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  // 告诉宿主页面已经能画：确保窗口可见并拿到焦点（Esc 才能进来）。
  void bridge.showPingCapture().catch(cause => {
    console.error('[capture] show failed', cause)
  })
  heartbeat = window.setInterval(() => {
    void bridge.heartbeatPingCapture().catch(() => undefined)
  }, 800)
})

onBeforeUnmount(() => {
  generation++
  activeClient?.close()
  activeClient = null
  window.removeEventListener('keydown', onKeydown)
  if (heartbeat) window.clearInterval(heartbeat)
  // 窗口关掉就把这条直调通道一起收掉，不留下半开的 WebSocket。
  void translateTransport?.close()
  translateTransport = null
})
</script>

<template>
  <CaptureEditor
    v-if="frame"
    :frame="frame"
    :busy="busy"
    :preset-region="initialRegion"
    :error="error"
    :translate="translateScreen"
    @cancel="cancel"
    @send="send"
  />
  <div v-else class="capture-boot">
    <div class="capture-boot__card">
      <div class="capture-boot__title">{{ bootError ? '截图打开失败' : '正在读取截图…' }}</div>
      <div v-if="bootError" class="capture-boot__error">{{ bootError }}</div>
      <button v-if="bootError" type="button" class="capture-boot__close" @click="cancel">关闭（Esc）</button>
    </div>
  </div>
</template>

<style scoped>
.capture-boot {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: #05070a;
  color: #eef3fb;
}

.capture-boot__card {
  min-width: 280px;
  max-width: min(560px, 80vw);
  padding: 20px 24px;
  border: 1px solid rgba(238, 243, 251, 0.14);
  border-radius: 14px;
  background: rgba(20, 23, 28, 0.94);
  text-align: center;
}

.capture-boot__title {
  font-size: 14px;
  font-weight: 600;
}

.capture-boot__error {
  margin-top: 10px;
  color: #ffb4b4;
  font-size: 12px;
  line-height: 1.5;
}

.capture-boot__close {
  margin-top: 16px;
  padding: 7px 18px;
  border: 0;
  border-radius: 999px;
  background: rgba(238, 243, 251, 0.9);
  color: #14171c;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
</style>
