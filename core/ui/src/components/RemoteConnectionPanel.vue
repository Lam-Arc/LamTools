<template>
  <section class="remote-panel" data-remote-connection>
    <div class="remote-panel__head">
      <span class="remote-panel__title">{{ t("设备连接") }}</span>
      <span class="remote-panel__state" :class="{ 'is-on': serving || connected }">
        {{ connected ? t('已连接') : serving ? t('等待手机连接') : t('未连接') }}
      </span>
      <button class="remote-panel__link" type="button" :disabled="busy" @click="refresh">{{ t("刷新") }}</button>
    </div>

    <p v-if="error" class="remote-panel__error" role="alert">{{ error }}</p>

    <!-- 电脑：二维码就是全部入口；生成票据即开始接受连接。 -->
    <template v-if="isDesktop">
      <div v-if="ticket" class="remote-panel__pair">
        <div v-if="qrSvg" class="remote-panel__qr" v-html="qrSvg" aria-hidden="true"></div>
        <div class="remote-panel__pair-side">
          <p class="remote-panel__hint">{{ t("用 Sunday M 扫一下，首次连接会自动成为可信设备。") }}</p>
          <button
            class="remote-panel__ticket"
            type="button"
            :title="t('点击复制票据')"
            :aria-label="t('复制票据')"
            @click="copyTicket"
          >
            <code data-remote-ticket>{{ copied ? t("已复制") : ticket }}</code>
          </button>
          <div class="remote-panel__row">
            <button class="remote-panel__button" type="button" :disabled="busy" @click="createTicket">{{ t("换一张") }}</button>
            <button class="remote-panel__button" type="button" :disabled="busy" @click="stopServing">{{ t("停止") }}</button>
          </div>
        </div>
      </div>
      <button
        v-else
        class="remote-panel__button is-primary remote-panel__wide"
        type="button"
        :disabled="busy"
        @click="createTicket"
      >
        {{ busy ? t("正在生成…") : t("生成票据") }}
      </button>
    </template>

    <!-- 手机：扫码是主入口，粘贴票据是退路。 -->
    <template v-else>
      <div v-if="connected" class="remote-panel__row">
        <span class="remote-panel__hint">{{ t("已连到 {0}", { 0: shortId(peer) }) }}</span>
        <button class="remote-panel__button" type="button" :disabled="busy" @click="disconnect">{{ t("断开") }}</button>
      </div>
      <template v-else>
        <button
          class="remote-panel__button is-primary remote-panel__wide"
          type="button"
          :disabled="busy"
          @click="scan"
          data-remote-scan
        >
          {{ t("扫码连接") }}
        </button>
        <button class="remote-panel__link" type="button" :disabled="busy" data-remote-paste-toggle @click="pasting = !pasting">
          {{ pasting ? t("收起") : t("粘贴票据") }}
        </button>
        <template v-if="pasting">
          <textarea
            v-model="ticketInput"
            class="remote-panel__input"
            rows="2"
            spellcheck="false"
            :placeholder="t('sunday1:…')"
            data-remote-ticket-input
          />
          <button
            class="remote-panel__button"
            type="button"
            :disabled="busy || !ticketInput.trim()"
            @click="connect"
          >
            {{ t("连接") }}
          </button>
        </template>
      </template>
    </template>

    <!-- 没有可信设备时整块不出现，避免空状态占位。 -->
    <details v-if="devices.length" class="remote-panel__devices">
      <summary>{{ t("可信设备") }}<span>{{ devices.length }}</span></summary>
      <ul class="remote-panel__list">
        <li v-for="device in devices" :key="device.id" class="remote-panel__device">
          <span class="remote-panel__device-name" :title="device.id">{{ device.name || shortId(device.id) }}</span>
          <button class="remote-panel__revoke" type="button" :disabled="busy" @click="revoke(device.id)">{{ t("撤销") }}</button>
        </li>
      </ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onMounted, ref } from 'vue'

import { saveTicket } from '@/app/remoteSession.ts'

/**
 * 配对面板。
 *
 * user:“简化配对界面，桌面端和移动端都简化”+(电脑只有一个动作：生成二维码/票据，
 * 生成即开始接受连接，票据本身就是复制入口；手机只有一个主动作：扫码，手动粘贴
 * 收在次要入口里。可信设备没有就不占位置)。
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
const busy = ref(false)
const error = ref('')
const pasting = ref(false)
const copied = ref(false)

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
  try {
    const name = isDesktop.value ? 'PC' : 'Phone'
    const result = await call<{ peer?: string }>('p2p_connect', { ticket: ticketInput.value.trim(), name })
    connected.value = Boolean(result?.peer)
    peer.value = result?.peer ?? ''
    if (result?.peer) saveTicket(ticketInput.value.trim())
    // user:“两种模式可切换”+(通道在启动时选定，切换就是让界面按新通道重开一次；
    // 本机 Core 不受影响，重开后仍是同一个会话)。
    window.location.reload()
  } catch (cause) {
    error.value = String(cause)
    // 扫码扫到了但连不上时，把票据留下来让用户能重试。
    if (!isDesktop.value) pasting.value = true
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

onMounted(refresh)
</script>

<style scoped>
.remote-panel {
  display: grid;
  gap: var(--space-3);
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

.remote-panel__link {
  margin-left: auto;
  border: 0;
  padding: 2px 4px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 12px;
  opacity: .62;
  cursor: pointer;
}

.remote-panel__link:hover {
  opacity: 1;
}

.remote-panel__link:disabled {
  opacity: .32;
  cursor: default;
}

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

.remote-panel__button.is-primary {
  background: var(--theme-main-text);
  color: var(--theme-main-background);
  border-color: transparent;
  font-weight: 650;
}

.remote-panel__wide {
  width: 100%;
  padding: 10px 12px;
}

.remote-panel__revoke {
  padding: 3px 8px;
  font-size: 12px;
}

.remote-panel__hint,
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

.remote-panel__pair {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
  flex-wrap: wrap;
}

.remote-panel__pair-side {
  display: grid;
  flex: 1 1 220px;
  gap: var(--space-2);
  min-width: 0;
}

.remote-panel__ticket {
  display: block;
  width: 100%;
  padding: 6px 8px;
  border: 0;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.remote-panel__ticket code {
  display: block;
  min-width: 0;
  font: 12px/1.5 ui-monospace, monospace;
  overflow-wrap: anywhere;
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
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  padding-top: var(--space-2);
}

.remote-panel__devices summary {
  display: flex;
  gap: var(--space-2);
  font-size: 12px;
  opacity: .72;
  cursor: pointer;
}

.remote-panel__list {
  display: grid;
  gap: var(--space-1);
  margin: var(--space-2) 0 0;
  padding: 0;
  list-style: none;
}

.remote-panel__device {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.remote-panel__device-name {
  flex: 1;
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
