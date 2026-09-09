<template>
  <section class="pairing-screen" aria-labelledby="pairing-title">
    <header class="pairing-screen__header">
      <h1 id="pairing-title">{{ authMode === 'login' ? '登录 LamTools' : '注册 LamTools' }}</h1>
      <button v-if="closable" class="pairing-screen__close" type="button" aria-label="关闭" @click="$emit('close')">×</button>
    </header>

    <section class="pairing-screen__account-card">
      <template v-if="accountSession">
        <div class="pairing-screen__account-user">
          <span>
            <strong>{{ accountSession.username }}</strong>
            <small>已登录</small>
          </span>
          <button type="button" :disabled="accountLoading" @click="$emit('account-logout')">退出</button>
        </div>

        <section class="pairing-screen__account-devices" aria-labelledby="account-devices-title">
          <div class="pairing-screen__section-title">
            <strong id="account-devices-title">设备与工作环境</strong>
            <small>{{ onlineAccountDeviceCount }}/{{ accountDeviceRows.length }} 在线</small>
          </div>
          <div v-if="accountDeviceRows.length" class="pairing-screen__workspace-list">
            <button
              v-for="device in accountDeviceRows"
              :key="device.nodeId"
              class="pairing-screen__workspace pairing-screen__account-device"
              :class="{ active: device.active }"
              type="button"
              :disabled="!device.workspaceId"
              @click="device.workspaceId && $emit('workspace-select', device.workspaceId)"
            >
              <component :is="device.desktop ? Monitor : Smartphone" :size="17" :stroke-width="1.8" aria-hidden="true" />
              <span>
                <strong>{{ device.label }}</strong>
                <small>{{ device.detail }}</small>
              </span>
              <span class="pairing-screen__device-state" :class="{ offline: !device.online }">
                <i aria-hidden="true" />{{ device.online ? '在线' : '离线' }}
              </span>
            </button>
          </div>
          <p v-else class="pairing-screen__empty">这个账号还没有已登记设备。</p>
        </section>
      </template>

      <form v-else class="pairing-screen__account-form" @submit.prevent="submitAccount">
        <input
          v-model="username"
          type="text"
          required
          minlength="3"
          maxlength="32"
          autocomplete="username"
          placeholder="用户名"
        />
        <input
          v-model="password"
          type="password"
          required
          minlength="8"
          autocomplete="current-password"
          placeholder="密码"
        />
        <p v-if="accountError" class="pairing-screen__error" role="alert">{{ accountError }}</p>
        <button class="pairing-screen__submit" type="submit" :disabled="accountLoading || !accountReady">
          {{ accountLoading ? '请稍候…' : (authMode === 'login' ? '确认登录' : '确认注册') }}
        </button>
        <button class="pairing-screen__mode-toggle" type="button" :disabled="accountLoading" @click="toggleAuthMode">
          {{ authMode === 'login' ? '转到注册' : '返回登录' }}
        </button>
      </form>
    </section>

    <button class="pairing-screen__more-toggle" type="button" :aria-expanded="moreOpen" @click="moreOpen = !moreOpen">
      <span>更多</span><span aria-hidden="true">{{ moreOpen ? '−' : '+' }}</span>
    </button>

    <section v-if="moreOpen" class="pairing-screen__more">
      <label class="pairing-screen__input-label" for="server-url">服务器地址（高级覆盖）</label>
      <input id="server-url" v-model="serverUrl" class="pairing-screen__text-input" type="url" autocomplete="url" placeholder="已使用内置服务器，可留空" />

      <form class="pairing-screen__form" @submit.prevent="submitPairing">
        <div class="pairing-screen__section-title"><strong>数字配对</strong><small>六位数字码</small></div>
        <label class="pairing-screen__input-label" for="gateway-url">手动网关（可选）</label>
        <input id="gateway-url" v-model="gatewayUrlValue" class="pairing-screen__text-input" type="text" inputmode="url" autocomplete="url" placeholder="http://电脑IP:端口" @change="emitGatewayUrl" />
        <input id="pairing-code" ref="codeInput" v-model="pairingCode" class="pairing-screen__input" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" placeholder="000000" aria-label="六位配对码" @input="normalizeInput" />
        <p v-if="pairingError" class="pairing-screen__error" role="alert">{{ pairingError }}</p>
        <button class="pairing-screen__submit" type="submit" :disabled="loading || !isReady">{{ pairingLoading ? '正在配对…' : '完成配对' }}</button>
      </form>

      <div v-if="trustedDevices.length" class="pairing-screen__list-block">
        <div class="pairing-screen__section-title"><strong>可信设备</strong><small>{{ trustedDevices.length }} 台</small></div>
        <button v-for="device in trustedDevices" :key="device.deviceId" class="pairing-screen__device" type="button" :class="{ active: currentDevice?.deviceId === device.deviceId }" @click="$emit('select-device', device.deviceId)">
          <span><strong>{{ device.name }}</strong><small>{{ device.gatewayUrl ? '手动网关' : '自动发现' }}</small></span>
          <span aria-hidden="true">›</span>
        </button>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Monitor, Smartphone } from 'lucide-vue-next'
import { PairingClient, normalizePairingCode } from './PairingClient'
import type { AccountConnectionProvider, AccountNode, AccountSession, AccountWorkspace } from '../account'
import type { TrustedDevice } from './TrustedDevices'

export interface AccountAuthRequest {
  mode: 'login' | 'register'
  serverUrl: string
  username: string
  password: string
}

const props = withDefaults(defineProps<{
  currentDevice?: TrustedDevice | null
  trustedDevices?: TrustedDevice[]
  accountSession?: AccountSession | null
  account?: AccountConnectionProvider | null
  workspaces?: AccountWorkspace[]
  accountNodes?: AccountNode[]
  accountLoading?: boolean
  accountError?: string
  gatewayUrl?: string
  closable?: boolean
}>(), {
  currentDevice: null,
  trustedDevices: () => [],
  accountSession: null,
  account: null,
  workspaces: () => [],
  accountNodes: () => [],
  accountLoading: false,
  accountError: '',
  gatewayUrl: '',
  closable: true,
})

const emit = defineEmits<{
  close: []
  paired: [device: TrustedDevice]
  'select-device': [deviceId: string]
  'forget-device': [deviceId: string]
  'gateway-url-change': [value: string]
  'account-authenticate': [request: AccountAuthRequest]
  'workspace-select': [workspaceId: string]
  'account-logout': []
}>()

const pairingCode = ref('')
const pairingLoading = ref(false)
const pairingError = ref('')
const codeInput = ref<HTMLInputElement | null>(null)
const gatewayUrlValue = ref(props.gatewayUrl)
const DEFAULT_SERVER_URL = 'wss://47.114.43.99.nip.io/v1/relay'
const configuredServerUrl = import.meta.env.VITE_LAMTOOLS_RELAY_URL || DEFAULT_SERVER_URL
const serverUrl = ref(configuredServerUrl)
const username = ref('')
const password = ref('')
const authMode = ref<'login' | 'register'>('login')
const moreOpen = ref(false)

const loading = computed(() => pairingLoading.value || props.accountLoading)
const isReady = computed(() => /^\d{6}$/.test(pairingCode.value))
const accountReady = computed(() => Boolean(username.value.trim() && password.value.length >= 8))

const accountDeviceRows = computed(() => props.accountNodes
  .filter((node) => !node.revokedAtMs)
  .map((node) => {
    const workspace = props.workspaces.find((item) => item.hostNodeId === node.nodeId)
    const desktop = Boolean(workspace || node.capabilities.includes('workspace_host') || /desktop|windows|macos|linux/i.test(node.platform))
    const currentMobile = node.nodeId === props.accountSession?.nodeId
    const active = node.nodeId === props.currentDevice?.deviceId
    return {
      nodeId: node.nodeId,
      workspaceId: workspace?.workspaceId || '',
      desktop,
      active,
      online: currentMobile || active || workspace?.online === true,
      label: workspace?.displayName || node.displayName,
      detail: active
        ? '当前控制的工作环境'
        : currentMobile
          ? '当前移动设备'
          : (desktop ? '桌面端工作环境' : '移动设备'),
    }
  })
  .sort((left, right) => Number(right.active) - Number(left.active) || Number(right.online) - Number(left.online)))

const onlineAccountDeviceCount = computed(() => accountDeviceRows.value.filter((device) => device.online).length)

watch(() => props.gatewayUrl, (value) => { gatewayUrlValue.value = value })

function normalizeInput(): void {
  pairingCode.value = normalizePairingCode(pairingCode.value)
  if (pairingError.value) pairingError.value = ''
}

function emitGatewayUrl(): void {
  emit('gateway-url-change', gatewayUrlValue.value)
}

async function submitPairing(): Promise<void> {
  if (!isReady.value || loading.value) return
  emitGatewayUrl()
  pairingLoading.value = true
  pairingError.value = ''
  try {
    const device = await new PairingClient({
      gatewayUrl: gatewayUrlValue.value,
      account: props.account || undefined,
    }).redeem(pairingCode.value)
    emit('paired', device)
    emit('close')
  } catch (reason) {
    pairingError.value = reason instanceof Error ? reason.message : String(reason)
    await nextTick()
    codeInput.value?.focus()
    codeInput.value?.select()
  } finally {
    pairingLoading.value = false
  }
}

function submitAccount(): void {
  if (!accountReady.value || loading.value) return
  emit('account-authenticate', {
    mode: authMode.value,
    serverUrl: serverUrl.value.trim() || configuredServerUrl,
    username: username.value.trim(),
    password: password.value,
  })
}

function toggleAuthMode(): void {
  authMode.value = authMode.value === 'login' ? 'register' : 'login'
}
</script>

<style scoped>
.pairing-screen {
  --text: var(--theme-main-text);
  display: grid;
  gap: var(--space-3);
  width: min(100%, 420px);
  max-height: min(100dvh, 900px);
  box-sizing: border-box;
  overflow: auto;
  padding: var(--space-5);
  color: var(--text);
  background: var(--theme-main-background);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}
.pairing-screen__header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.pairing-screen h1 { margin: 0; font-size: 20px; }
.pairing-screen__current { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) 0; border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); border-bottom: 1px solid color-mix(in srgb, var(--text) 12%, transparent); }
.pairing-screen__current > div, .pairing-screen__account-user > span, .pairing-screen__device > span:first-child, .pairing-screen__workspace > span:first-child { display: grid; gap: var(--space-1); min-width: 0; }
.pairing-screen__current small, .pairing-screen__input-hint, .pairing-screen__section-title small, .pairing-screen__device small, .pairing-screen__workspace small, .pairing-screen__account-user small { color: color-mix(in srgb, var(--text) 55%, transparent); }
.pairing-screen__current strong, .pairing-screen__device strong, .pairing-screen__workspace strong, .pairing-screen__account-user strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.pairing-screen__current button, .pairing-screen__account-user button { min-height: 34px; padding: 0 var(--space-2); border: 1px solid color-mix(in srgb, var(--red) 30%, transparent); border-radius: var(--radius-sm); background: transparent; color: var(--red); font: inherit; cursor: pointer; }
.pairing-screen__current button:disabled, .pairing-screen__account-user button:disabled { opacity: .45; cursor: not-allowed; }
.pairing-screen__close { width: 32px; height: 32px; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--text); font-size: 22px; cursor: pointer; }
.pairing-screen__close:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); }
.pairing-screen__form, .pairing-screen__account-form { display: grid; gap: var(--space-2); }
.pairing-screen__section-title { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); }
.pairing-screen__section-title strong { font-size: 14px; }
.pairing-screen__section-title small { font-size: 11px; }
.pairing-screen__input-label { color: color-mix(in srgb, var(--text) 72%, transparent); font-size: 12px; font-weight: 650; }
.pairing-screen__text-input, .pairing-screen__account-form input { width: 100%; min-height: 42px; box-sizing: border-box; padding: 0 var(--space-3); border: 1px solid color-mix(in srgb, var(--theme-control-text) 14%, transparent); border-radius: var(--radius-sm); outline: 0; background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); font: inherit; font-size: 13px; }
.pairing-screen__text-input:focus, .pairing-screen__input:focus, .pairing-screen__account-form input:focus { outline: 0; }
.pairing-screen__input { width: 100%; box-sizing: border-box; min-height: 58px; padding: 0 var(--space-3); border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent); border-radius: var(--radius); outline: 0; background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); font-family: var(--font-mono); font-size: 30px; font-weight: 700; letter-spacing: .22em; text-align: center; text-indent: .22em; }
.pairing-screen__input-hint { font-size: 11px; line-height: 1.5; }
.pairing-screen__error { margin: 0; color: var(--red); font-size: 12px; line-height: 1.5; }
.pairing-screen__submit { min-height: 44px; margin-top: var(--space-2); border: 0; border-radius: var(--radius-sm); background: var(--theme-control-background); color: var(--theme-control-text); font: inherit; font-weight: 650; cursor: pointer; }
.pairing-screen__submit--secondary { margin-top: var(--space-1); }
.pairing-screen__submit:hover { filter: brightness(.94); }
.pairing-screen__submit:disabled { opacity: .45; cursor: not-allowed; }
.pairing-screen__list-block, .pairing-screen__account { display: grid; gap: var(--space-2); padding-top: var(--space-3); border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); }
.pairing-screen__device, .pairing-screen__workspace { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); width: 100%; padding: var(--space-3); border: 1px solid color-mix(in srgb, var(--text) 10%, transparent); border-radius: var(--radius-sm); background: transparent; color: var(--text); text-align: left; font: inherit; cursor: pointer; }
.pairing-screen__device:hover, .pairing-screen__workspace:hover, .pairing-screen__device.active, .pairing-screen__workspace.active { border-color: color-mix(in srgb, var(--blue) 38%, transparent); background: color-mix(in srgb, var(--blue) 7%, transparent); }
.pairing-screen__device > span:last-child { color: color-mix(in srgb, var(--text) 48%, transparent); font-size: 20px; }
.pairing-screen__account-user { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding-bottom: var(--space-2); }
.pairing-screen__account-devices { display: grid; gap: var(--space-2); padding-top: var(--space-3); border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); }
.pairing-screen__workspace-list { display: grid; gap: var(--space-2); }
.pairing-screen__workspace { align-items: center; }
.pairing-screen__account-device { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; }
.pairing-screen__account-device:disabled { opacity: 1; cursor: default; }
.pairing-screen__account-device.active { border-color: color-mix(in srgb, var(--green) 38%, transparent); background: color-mix(in srgb, var(--green) var(--alpha-hover), transparent); }
.pairing-screen__device-state { display: inline-flex; align-items: center; gap: var(--space-1); color: var(--green); font-size: 11px; white-space: nowrap; }
.pairing-screen__device-state i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.pairing-screen__device-state.offline { color: color-mix(in srgb, var(--text) 42%, transparent); }
.pairing-screen__online-dot { flex: 0 0 auto; width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 4px color-mix(in srgb, var(--green) 14%, transparent); }
.pairing-screen__online-dot.offline { background: color-mix(in srgb, var(--text) 38%, transparent); box-shadow: none; }
.pairing-screen__empty, .pairing-screen__password-note { margin: 0; color: color-mix(in srgb, var(--text) 58%, transparent); font-size: 11px; line-height: 1.5; }
.pairing-screen__mode-toggle { min-height: 32px; border: 0; background: transparent; color: color-mix(in srgb, var(--blue) 78%, var(--text)); font: inherit; font-size: 12px; cursor: pointer; }
.pairing-screen__mode-toggle:disabled { opacity: .45; cursor: wait; }
.pairing-screen__account-card { display: grid; gap: var(--space-3); padding: var(--space-4); border: 1px solid color-mix(in srgb, var(--text) 10%, transparent); border-radius: var(--radius); background: color-mix(in srgb, var(--theme-control-background) 26%, var(--theme-main-background)); box-shadow: var(--shadow-sm); }
.pairing-screen__account-form { gap: var(--space-3); }
.pairing-screen__more-toggle { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 38px; padding: 0 var(--space-2); border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--text) 64%, transparent); font: inherit; font-size: 12px; cursor: pointer; }
.pairing-screen__more-toggle:hover, .pairing-screen__more-toggle[aria-expanded="true"] { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.pairing-screen__more { display: grid; gap: var(--space-3); padding-top: var(--space-3); border-top: 1px solid color-mix(in srgb, var(--text) 10%, transparent); }

@media (max-width: 640px) {
  .pairing-screen { width: min(100%, 420px); max-height: calc(100dvh - var(--space-6)); padding: var(--space-4); }
  .pairing-screen__section-title { align-items: flex-start; flex-direction: column; gap: var(--space-1); }
}
</style>
