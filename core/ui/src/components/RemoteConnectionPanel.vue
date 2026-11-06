<template>
  <section class="remote-panel" data-remote-connection>
    <div class="remote-panel__head">
      <span class="remote-panel__title">{{ t("设备连接") }}</span>
      <span class="remote-panel__state" :class="{ 'is-on': serving || connected }">
        {{ serving ? t('正在接受连接') : connected ? t('已连接') : t('未连接') }}
      </span>
      <button class="remote-panel__refresh" type="button" :disabled="busy" @click="refresh">{{ t("刷新") }}</button>
    </div>

    <p v-if="error" class="remote-panel__error" role="alert">{{ error }}</p>

    <!-- 电脑：出票据，手机来连 -->
    <template v-if="isDesktop">
      <p class="remote-panel__hint">{{ t("在手机上打开远程连接，粘贴这段票据。第一次连接会自动成为可信设备，之后不用再确认。") }}</p>
      <div class="remote-panel__pair">
        <!-- user:“设备配对：支持二维码、配对码等简单方式”+(二维码和下面那行文本是同一张票据)。 -->
        <div v-if="qrSvg" class="remote-panel__qr" v-html="qrSvg" aria-hidden="true"></div>
        <div class="remote-panel__pair-copy">
          <code class="remote-panel__ticket" data-remote-ticket>{{ ticket || t("还没有票据，点右边的按钮生成") }}</code>
          <div class="remote-panel__row">
            <button class="remote-panel__button" type="button" :disabled="busy" @click="createTicket">{{ ticket ? t("换一张") : t("生成票据") }}</button>
            <button v-if="ticket" class="remote-panel__button" type="button" @click="copyTicket">{{ t("复制票据") }}</button>
          </div>
        </div>
      </div>
      <div class="remote-panel__row">
        <button v-if="!serving" class="remote-panel__button is-primary" type="button" :disabled="busy || !ticket" @click="serveStart">{{ t("开始接受连接") }}</button>
        <button v-else class="remote-panel__button" type="button" :disabled="busy" @click="serveStop">{{ t("停止接受连接") }}</button>
        <span class="remote-panel__note">{{ t("直连优先，打不通才走公共中继；任务在这台电脑上执行。") }}</span>
      </div>
    </template>

    <!-- 手机：粘贴票据去连电脑 -->
    <template v-else>
      <p class="remote-panel__hint">{{ t("从电脑的远程连接页复制票据，粘贴到这里。连上之后，会话、工具和审批都在电脑上跑。") }}</p>
      <textarea
        v-model="ticketInput"
        class="remote-panel__input"
        rows="3"
        spellcheck="false"
        :placeholder="t('sunday1:…')"
        data-remote-ticket-input
      />
      <div class="remote-panel__row">
        <button v-if="!connected" class="remote-panel__button is-primary" type="button" :disabled="busy || !ticketInput.trim()" @click="connect">{{ t("连接") }}</button>
        <button v-else class="remote-panel__button" type="button" :disabled="busy" @click="disconnect">{{ t("断开") }}</button>
        <span v-if="peer" class="remote-panel__note">{{ t("已连到 {0}", { 0: shortId(peer) }) }}</span>
      </div>
    </template>

    <div class="remote-panel__devices">
      <div class="remote-panel__devices-title">{{ t("可信设备") }}<span>{{ devices.length }}</span></div>
      <ul v-if="devices.length" class="remote-panel__list">
        <li v-for="device in devices" :key="device.id" class="remote-panel__device">
          <span class="remote-panel__device-name">{{ device.name || shortId(device.id) }}</span>
          <code class="remote-panel__device-id">{{ shortId(device.id) }}</code>
          <button class="remote-panel__revoke" type="button" :disabled="busy" @click="revoke(device.id)">{{ t("撤销") }}</button>
        </li>
      </ul>
      <p v-else class="remote-panel__empty">{{ t("还没有可信设备。配对一次就会出现在这里，撤销后立刻失效。") }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onMounted, ref } from 'vue'

/**
 * 设备连接面板。
 *
 * user:“把「周几 / 账号」换成 Sunday / Sunday M 远程连接”+(这一块只说连接：本机票据、
 * 对方的票据、可信设备；不解释账号，也不需要登录)。
 *
 * 命令由宿主提供：桌面是 p2p_ticket / p2p_serve_start / …，手机是 p2p_connect / p2p_call /
 * …。这里只做界面，协议与身份都在 core/p2p。
 */
const props = defineProps<{ platform?: 'desktop' | 'mobile' | 'web' }>()

const ticket = ref('')
const qrSvg = ref('')
const ticketInput = ref('')
const serving = ref(false)
const connected = ref(false)
const peer = ref('')
const devices = ref<Array<{ id: string; name: string }>>([])
const busy = ref(false)
const error = ref('')

const isDesktop = computed(() => (props.platform ?? 'desktop') === 'desktop')

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
    const list = await call<{ devices?: Array<{ id: string; name: string }> }>('p2p_devices')
    devices.value = list?.devices ?? []
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function refreshQr(value: string): Promise<void> {
  qrSvg.value = ''
  if (!value) return
  try {
    const result = await call<{ svg?: string }>('p2p_qr', { ticket: value })
    qrSvg.value = result?.svg ?? ''
  } catch {
    // A missing QR only costs convenience: the ticket text is right above it.
  }
}

async function copyTicket(): Promise<void> {
  try {
    await navigator.clipboard.writeText(ticket.value)
  } catch {
    // Clipboard unavailable: the text is selectable anyway.
  }
}

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
      await refreshQr(ticket.value)
    }
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function serveStart(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const apiBase = await call<string>('get_api_base')
    if (!apiBase) throw new Error(t('拿不到本地后端地址'))
    await call('p2p_serve_start', { apiBase })
    serving.value = true
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function serveStop(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await call('p2p_serve_stop')
    serving.value = false
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function connect(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const name = isDesktop.value ? 'PC' : 'Phone'
    const result = await call<{ peer?: string }>('p2p_connect', { ticket: ticketInput.value.trim(), name })
    connected.value = Boolean(result?.peer)
    peer.value = result?.peer ?? ''
    // user:“两种模式可切换”+(通道在启动时选定，切换就是让界面按新通道重开一次；
    // 本机 Core 不受影响，重开后仍是同一个会话)。
    window.location.reload()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = false
  }
}

async function disconnect(): Promise<void> {
  busy.value = true
  try {
    await call('p2p_disconnect')
    connected.value = false
    peer.value = ''
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

onMounted(refresh)
</script>

<style scoped>
.remote-panel {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--theme-main-text) 3%, transparent);
}

.remote-panel__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.remote-panel__title {
  font-weight: 650;
}

.remote-panel__state {
  font-size: 12px;
  opacity: .62;
}

.remote-panel__state.is-on {
  color: var(--green);
  opacity: 1;
}

.remote-panel__refresh,
.remote-panel__button,
.remote-panel__revoke {
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  padding: 6px 10px;
  font: inherit;
  cursor: pointer;
}

.remote-panel__refresh {
  margin-left: auto;
}

.remote-panel__button.is-primary {
  background: var(--theme-main-text);
  color: var(--theme-main-background);
  border-color: transparent;
  font-weight: 650;
}

.remote-panel__revoke {
  padding: 3px 8px;
  font-size: 12px;
}

.remote-panel__hint,
.remote-panel__note,
.remote-panel__empty {
  margin: 0;
  font-size: 12px;
  opacity: .66;
  line-height: 1.5;
}

.remote-panel__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.remote-panel__ticket,
.remote-panel__device-id {
  flex: 1 1 240px;
  min-width: 0;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
  font: 12px/1.5 ui-monospace, monospace;
  overflow-wrap: anywhere;
}

.remote-panel__pair {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
  flex-wrap: wrap;
}

.remote-panel__qr {
  flex: 0 0 auto;
  width: 148px;
  height: 148px;
  padding: 6px;
  border-radius: var(--radius-sm);
  background: #ffffff;
}

.remote-panel__qr :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
}

.remote-panel__pair-copy {
  display: grid;
  flex: 1 1 240px;
  gap: var(--space-2);
  min-width: 0;
}

.remote-panel__input {
  width: 100%;
  padding: 8px;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  background: color-mix(in srgb, var(--theme-main-text) 4%, transparent);
  color: inherit;
  font: 12px/1.5 ui-monospace, monospace;
  resize: vertical;
}

.remote-panel__devices {
  display: grid;
  gap: var(--space-1);
  margin-top: var(--space-1);
}

.remote-panel__devices-title {
  display: flex;
  gap: var(--space-2);
  font-size: 12px;
  opacity: .72;
}

.remote-panel__list {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.remote-panel__device {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.remote-panel__device-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remote-panel__error {
  margin: 0;
  color: var(--red);
  font-size: 12px;
}
</style>
