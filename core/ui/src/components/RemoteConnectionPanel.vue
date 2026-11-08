<template>
  <section class="device-page" data-remote-connection>
    <header class="device-page__head">
      <div class="device-page__intro">
        <h2 class="device-page__title">{{ t("设备连接") }}</h2>
        <p class="device-page__sub">
          {{ isDesktop
            ? t("手机扫这里，就能接手这台电脑上的会话。")
            : t("选择在哪里工作：这台手机，或一台配对过的电脑。") }}
        </p>
      </div>
      <button class="device-page__refresh" type="button" :disabled="busy" @click="refresh">
        <RefreshCw :size="14" :stroke-width="2" aria-hidden="true" />
        {{ t("刷新") }}
      </button>
    </header>

    <p v-if="error" class="device-page__error" role="alert">{{ error }}</p>

    <!-- 手机：设备清单。切换就发生在这里，输入框上方不再有第二个入口。 -->
    <template v-if="!isDesktop">
      <ul class="device-list">
        <li
          class="device-item"
          :class="{ 'is-active': activeId === 'local' }"
          @click="onRowClick('local')"
        >
          <span class="device-item__icon"><Smartphone :size="18" :stroke-width="1.9" aria-hidden="true" /></span>
          <span class="device-item__body">
            <span class="device-item__name">{{ t("本机") }}</span>
            <span class="device-item__meta">{{ t("这台手机 · 不需要连接") }}</span>
          </span>
          <span v-if="activeId === 'local'" class="device-item__badge is-here">{{ t("当前") }}</span>
          <button
            v-else
            class="device-item__action"
            type="button"
            :disabled="busy"
            data-device-switch="local"
            @click="switchTo('local')"
          >
            {{ t("切到本机") }}
          </button>
        </li>

        <li
          v-for="entry in paired"
          :key="entry.id"
          class="device-item"
          :class="{ 'is-active': activeId === entry.id }"
          @click="onRowClick(entry.id)"
        >
          <span class="device-item__icon"><Monitor :size="18" :stroke-width="1.9" aria-hidden="true" /></span>
          <span class="device-item__body">
            <span class="device-item__name">{{ entry.name }}</span>
            <span class="device-item__meta">
              {{ t("电脑 · 已配对") }}
              <template v-if="connected && peer === entry.id"> · {{ t("连接正常") }}</template>
              <template v-else-if="connected && peer !== entry.id"> · {{ t("未连接") }}</template>
            </span>
          </span>
          <span v-if="activeId === entry.id" class="device-item__badge is-here">{{ t("当前") }}</span>
          <button
            v-else
            class="device-item__action"
            type="button"
            :disabled="busy"
            :data-device-switch="entry.id"
            @click="switchTo(entry.id)"
          >
            {{ t("切换") }}
          </button>
        </li>

        <li v-if="paired.length === 0" class="device-list__empty">
          {{ t("还没有配对的电脑。在电脑上打开「远程连接」生成二维码，然后下方扫码。") }}
        </li>
      </ul>

      <div class="device-page__actions">
        <button
          class="device-page__button is-primary"
          type="button"
          :disabled="busy"
          data-remote-scan
          @click="scan"
        >
          <QrCode :size="16" :stroke-width="2" aria-hidden="true" />
          {{ t("扫码连接电脑") }}
        </button>
        <button
          class="device-page__button"
          type="button"
          :disabled="busy"
          data-remote-paste-toggle
          @click="pasting = !pasting"
        >
          {{ pasting ? t("收起票据") : t("粘贴票据") }}
        </button>
      </div>

      <p v-if="busy && progressText" class="device-page__progress" role="status">
        {{ progressText }}（{{ t("已等待 {0} 秒", { 0: elapsed }) }}）
      </p>

      <div v-if="pasting" class="device-page__paste">
        <textarea
          v-model="ticketInput"
          rows="3"
          spellcheck="false"
          :placeholder="t('sunday1:…')"
          data-remote-ticket-input
        />
        <button
          class="device-page__button is-primary"
          type="button"
          :disabled="busy || !ticketInput.trim()"
          @click="connect"
        >
          {{ t("连接这台电脑") }}
        </button>
      </div>
    </template>

    <!-- 电脑：二维码就是全部入口；生成票据即开始接受连接。 -->
    <template v-else>
      <div v-if="ticket" class="pair-card">
        <div v-if="qrSvg" class="pair-card__qr" v-html="qrSvg" aria-hidden="true"></div>
        <div class="pair-card__side">
          <p class="pair-card__hint">{{ t("用 Sunday M 扫一下，首次连接会自动成为可信设备。") }}</p>
          <button
            class="pair-card__ticket"
            type="button"
            :title="t('点击复制票据')"
            :aria-label="t('复制票据')"
            @click="copyTicket"
          >
            <code data-remote-ticket>{{ copied ? t("已复制") : ticket }}</code>
          </button>
          <div class="device-page__actions">
            <button class="device-page__button" type="button" :disabled="busy" @click="createTicket">{{ t("换一张") }}</button>
            <button class="device-page__button" type="button" :disabled="busy" @click="stopServing">{{ t("停止接受") }}</button>
          </div>
        </div>
      </div>
      <button
        v-else
        class="device-page__button is-primary is-wide"
        type="button"
        :disabled="busy"
        @click="createTicket"
      >
        {{ busy ? t("正在生成…") : t("生成配对二维码") }}
      </button>

      <div v-if="connected" class="device-page__note">
        {{ t("手机已连上这台电脑。") }}
        <button class="device-page__link" type="button" :disabled="busy" @click="disconnect">{{ t("断开") }}</button>
      </div>
    </template>

    <p v-if="!isDesktop" class="device-page__foot">
      {{ t("电脑上打开 Sunday，进入「远程连接」生成二维码，再用这里扫码；第一次连上之后，这台手机会记住它。") }}
    </p>

    <!-- 没有可信设备时整块不出现，避免空状态占位。 -->
    <details v-if="devices.length" class="device-page__trusted">
      <summary>{{ t("可信设备") }} <span>{{ devices.length }}</span></summary>
      <ul>
        <li v-for="device in devices" :key="device.id">
          <span :title="device.id">{{ device.name || shortId(device.id) }}</span>
          <button type="button" :disabled="busy" @click="revoke(device.id)">{{ t("撤销") }}</button>
        </li>
      </ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Monitor, QrCode, RefreshCw, Smartphone } from 'lucide-vue-next'

import {
  activateDevice,
  readDevices,
  readTicket,
  rememberDevice,
  saveTicket,
  type PairedDevice,
} from '@/app/remoteSession.ts'

/**
 * 设备连接页。
 *
 * user:“工作环境的切换从输入框挪到设备连接那个页面”“设备连接页面你也要重做一遍，
 * 现在的样式太普通了，不易用”+(所以这一页的主体是设备清单：本机一行、每台配对过的
 * 电脑一行，行内直接切换；扫码与粘贴退到清单下面当“添加设备”，不再是首屏唯一动作)。
 *
 * 命令由宿主提供：桌面是 p2p_ticket / p2p_qr / …，手机是 p2p_scan / p2p_connect / …。
 * 这里只做界面，协议与身份都在 core/p2p。
 */
const props = defineProps<{ platform?: 'desktop' | 'mobile' | 'web' }>()

const ticket = ref('')
const qrSvg = ref('')
const ticketInput = ref('')
const serving = ref(false)
const connected = ref(false)
const peer = ref('')
const devices = ref<Array<{ id: string; name: string }>>([])
const paired = ref<PairedDevice[]>([])
const busy = ref(false)
const error = ref('')
const pasting = ref(false)
const copied = ref(false)
const elapsed = ref(0)
const progressText = ref('')
let progressTimer: number | null = null

const isDesktop = computed(() => (props.platform ?? 'desktop') === 'desktop')
/** 当前在哪一台设备上工作：连着电脑就是对端 id，否则本机。 */
/**
 * 界面此刻真正在用的工作环境（不是隧道状态）。
 *
 * user:“我切到本机之后它又变回去了”+(以前这里用 connected && peer 推断，隧道一连上就
 * 认为当前是电脑，可界面走的是启动时选定的通道，两者能同时成立又互相矛盾)。
 * 启动流程会把实际选择写进 localStorage，这里照它显示。
 */
const activeId = computed(() => {
  try {
    return localStorage.getItem('sunday.p2p.active') || 'local'
  } catch {
    return 'local'
  }
})

/** 点整行就能切，不用先找到右边那颗按钮。 */
function onRowClick(id: string): void {
  if (busy.value || id === activeId.value) return
  void switchTo(id)
}

function host(): ((command: string, args?: Record<string, unknown>) => Promise<unknown>) | null {
  const bridge = (window as unknown as {
    __TAURI_INTERNALS__?: { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> }
  }).__TAURI_INTERNALS__
  return bridge ? bridge.invoke.bind(bridge) : null
}

async function call<T>(command: string, args?: Record<string, unknown>): Promise<T | null> {
  const invoke = host()
  if (!invoke) return null
  return (await invoke(command, args)) as T
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id
}

function loadPaired(): void {
  paired.value = readDevices()
}

async function refresh(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const status = await call<{ serving?: boolean; ticket?: string; connected?: boolean; peer?: string | null }>('p2p_status')
    if (status) {
      serving.value = status.serving === true
      connected.value = status.connected === true
      peer.value = status.peer ?? ''
      if (status.ticket && status.ticket !== ticket.value) {
        ticket.value = status.ticket
        await refreshQr(ticket.value)
      }
    }
    loadPaired()
    const list = await call<{ devices?: Array<{ id: string; name: string }> }>('p2p_devices')
    devices.value = list?.devices ?? []
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/**
 * 静默轮询连接状态。
 *
 * user:“连上了电脑，但是它弹了一个错误”“我根本不知道卡在哪里了”+(手机连上或者断开，
 * 电脑这边应当自己变，而不是让用户盯着二维码猜；断开之后也还留着上一台的残影)。
 */
async function refreshQuiet(): Promise<void> {
  if (busy.value) return
  try {
    const status = await call<{ serving?: boolean; connected?: boolean; peer?: string | null }>('p2p_status')
    if (!status) return
    serving.value = status.serving === true
    connected.value = status.connected === true
    peer.value = status.peer ?? ''
    loadPaired()
  } catch {
    // 轮询失败不打断用户正在做的事。
  }
}

async function refreshQr(value: string): Promise<void> {
  qrSvg.value = ''
  if (!value) return
  try {
    const result = await call<{ svg?: string }>('p2p_qr', { ticket: value })
    qrSvg.value = result?.svg ?? ''
  } catch {
    // 二维码只是方便，票据文字本身还能复制。
  }
}

async function copyTicket(): Promise<void> {
  try {
    await navigator.clipboard.writeText(ticket.value)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1500)
  } catch {
    // 剪贴板不可用时票据文字仍可手动选择。
  }
}

/** 从票据里取出直连地址与中继，用于说明这次会先试什么。 */
function describeTicket(value: string): { ip: string; relay: boolean } {
  try {
    const body = value.trim().replace(/^sunday1:/, '')
    const padded = body.replace(/-/g, '+').replace(/_/g, '/')
      + '='.repeat((4 - (body.length % 4)) % 4)
    const parsed = JSON.parse(atob(padded)) as { addrs?: Array<{ Ip?: string; Relay?: string }> }
    return {
      ip: parsed.addrs?.find((item) => typeof item.Ip === 'string')?.Ip ?? '',
      relay: Boolean(parsed.addrs?.some((item) => typeof item.Relay === 'string')),
    }
  } catch {
    return { ip: '', relay: false }
  }
}

/** user:“连接过程中一点反应都没有”+(连接期间说明先试哪条路，并显示已等待时间)。 */
function startConnecting(value: string): void {
  const { ip, relay } = describeTicket(value)
  progressText.value = ip && relay
    ? t('正在连接：先试直连 {0}，失败自动走中继', { 0: ip })
    : ip
      ? t('正在直连 {0}', { 0: ip })
      : t('正在通过中继连接')
  elapsed.value = 0
  if (progressTimer !== null) window.clearInterval(progressTimer)
  progressTimer = window.setInterval(() => {
    elapsed.value += 1
  }, 1000)
}

function stopConnecting(): void {
  if (progressTimer !== null) {
    window.clearInterval(progressTimer)
    progressTimer = null
  }
  progressText.value = ''
  elapsed.value = 0
}

/** 切换工作设备：先断掉现有隧道，再按新选择重开界面。 */
async function switchTo(id: string): Promise<void> {
  if (busy.value || id === activeId.value) return
  busy.value = true
  error.value = ''
  try {
    activateDevice(id === 'local' ? null : id)
    // user:“我怎么从控制电脑切回手机”+(只清票据不够：宿主里的隧道还连着，重开之后
    // 又会按「已连接」走回电脑。切换必须先断掉现有隧道)。
    await call('p2p_disconnect').catch(() => undefined)
    window.location.reload()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/** 生成票据即开始接受连接，不再让用户点第二次。 */
async function createTicket(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const args: Record<string, unknown> = {}
    if (isDesktop.value) {
      const apiBase = await call<string>('get_api_base')
      if (!apiBase) throw new Error(t('拿不到本地后端地址'))
      args.apiBase = apiBase
    }
    const result = await call<{ ticket?: string }>('p2p_ticket', args)
    if (result?.ticket) {
      ticket.value = result.ticket
      serving.value = true
      await refreshQr(ticket.value)
    }
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function stopServing(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await call('p2p_serve_stop')
    serving.value = false
    ticket.value = ''
    qrSvg.value = ''
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

/** 扫码成功就直接连，不再让用户点“连接”。 */
async function scan(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const result = await call<{ ticket?: string | null }>('p2p_scan')
    if (!result?.ticket) return
    ticketInput.value = result.ticket
    await connect()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function connect(): Promise<void> {
  busy.value = true
  error.value = ''
  startConnecting(ticketInput.value)
  try {
    const name = isDesktop.value ? 'PC' : 'Phone'
    const result = await call<{ peer?: string }>('p2p_connect', { ticket: ticketInput.value.trim(), name })
    connected.value = Boolean(result?.peer)
    peer.value = result?.peer ?? ''
    if (result?.peer) {
      saveTicket(ticketInput.value.trim())
      // 配过的电脑进设备清单，之后直接在清单里切换。
      rememberDevice(ticketInput.value.trim(), shortId(result.peer))
      loadPaired()
    }
    window.location.reload()
  } catch (cause) {
    error.value = String(cause)
    if (!isDesktop.value) pasting.value = true
  } finally {
    busy.value = false
    stopConnecting()
  }
}

async function disconnect(): Promise<void> {
  busy.value = true
  try {
    await call('p2p_disconnect')
    connected.value = false
    peer.value = ''
    saveTicket('')
    window.location.reload()
  } finally {
    busy.value = false
  }
}

async function revoke(id: string): Promise<void> {
  busy.value = true
  try {
    await call('p2p_revoke', { id })
    await refresh()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  void refresh()
  const timer = window.setInterval(() => {
    void refreshQuiet()
  }, 3000)
  onUnmounted(() => window.clearInterval(timer))
  if (!host()) return
  void import('@tauri-apps/api/event').then(async ({ listen }) => {
    try {
      await listen<{ phase?: string }>('p2p-progress', (event) => {
        const phase = event.payload?.phase
        if (phase === 'dialing') {
          if (!progressText.value) progressText.value = t('正在连接对方…')
        } else if (phase === 'connected') {
          progressText.value = t('已连上，正在切换到远程会话…')
        }
      })
    } catch {
      // 进度事件只是提示，缺了不影响连接。
    }
  })
})
</script>

<style scoped>
.device-page {
  display: grid;
  gap: var(--space-4);
}

.device-page__head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.device-page__intro {
  min-width: 0;
}

.device-page__title {
  margin: 0;
  font-size: 17px;
  font-weight: 650;
  letter-spacing: 0.01em;
}

.device-page__sub {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.6;
}

.device-page__refresh {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.device-page__refresh:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.device-page__refresh:disabled {
  opacity: 0.4;
  cursor: default;
}

.device-page__error {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red) 12%, transparent);
  color: var(--red);
  font-size: 12px;
  line-height: 1.6;
}

/* ── 设备清单 ─────────────────────────────────────────── */
.device-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.device-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--theme-main-text) 2.5%, transparent);
  transition: border-color 0.18s ease, background 0.18s ease;
}

.device-item.is-active {
  border-color: color-mix(in srgb, var(--theme-main-text) 26%, transparent);
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.device-item__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  border-radius: 12px;
  background: color-mix(in srgb, var(--theme-main-text) 7%, transparent);
  opacity: 0.85;
}

.device-item__body {
  display: grid;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.device-item__name {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-item__meta {
  font-size: 11.5px;
  line-height: 1.4;
  opacity: 0.55;
}

.device-item__badge {
  flex: 0 0 auto;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  letter-spacing: 0.04em;
}

.device-item__badge.is-here {
  background: color-mix(in srgb, var(--green) 18%, transparent);
  color: var(--green);
}

.device-item__action {
  flex: 0 0 auto;
  padding: 8px 14px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 16%, transparent);
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

.device-item__action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) 8%, transparent);
}

.device-item__action:disabled {
  opacity: 0.4;
  cursor: default;
}

.device-list__empty {
  padding: 18px 14px;
  border: 1px dashed color-mix(in srgb, var(--theme-main-text) 16%, transparent);
  border-radius: var(--radius);
  font-size: 12px;
  line-height: 1.7;
  opacity: 0.6;
}

/* ── 动作 ─────────────────────────────────────────────── */
.device-page__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.device-page__button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 16px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.device-page__button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.device-page__button.is-primary {
  background: var(--theme-main-text);
  border-color: transparent;
  color: var(--theme-main-background);
  font-weight: 650;
}

.device-page__button.is-wide {
  width: 100%;
}

.device-page__button:disabled {
  opacity: 0.45;
  cursor: default;
}

.device-page__foot {
  margin: 0;
  padding-top: 4px;
  font-size: 11.5px;
  line-height: 1.7;
  opacity: 0.42;
}

.device-page__progress {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.66;
}

.device-page__paste {
  display: grid;
  gap: 8px;
}

.device-page__paste textarea {
  width: 100%;
  padding: 10px;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  background: color-mix(in srgb, var(--theme-main-text) 4%, transparent);
  color: inherit;
  font: 12px/1.6 ui-monospace, monospace;
  resize: vertical;
}

.device-page__note {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  opacity: 0.72;
}

.device-page__link {
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
  opacity: 0.8;
}

/* ── 电脑端：二维码 ───────────────────────────────────── */
.pair-card {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
  padding: 14px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--theme-main-text) 2.5%, transparent);
}

.pair-card__qr {
  flex: 0 0 auto;
  width: 156px;
  height: 156px;
  padding: 6px;
  border-radius: var(--radius-sm);
  background: #ffffff;
}

.pair-card__qr :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
}

.pair-card__side {
  display: grid;
  flex: 1 1 220px;
  gap: 10px;
  min-width: 0;
}

.pair-card__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.66;
}

.pair-card__ticket {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.pair-card__ticket code {
  display: block;
  min-width: 0;
  font: 12px/1.5 ui-monospace, monospace;
  overflow-wrap: anywhere;
}

/* ── 可信设备 ─────────────────────────────────────────── */
.device-page__trusted {
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  padding-top: 10px;
}

.device-page__trusted summary {
  display: flex;
  gap: 8px;
  font-size: 12px;
  opacity: 0.66;
  cursor: pointer;
}

.device-page__trusted ul {
  display: grid;
  gap: 6px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.device-page__trusted li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.device-page__trusted li span {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.72;
}

.device-page__trusted li button {
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  padding: 3px 10px;
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
</style>
