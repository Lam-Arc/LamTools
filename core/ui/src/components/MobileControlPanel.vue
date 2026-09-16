<template>
  <section class="settings-panel mobile-control-panel">
    <header class="settings-title">
      <h1>手机控制</h1>
      <p>用 LamTools 手机端查看会话、继续任务并处理审批。Core 仍只监听本机地址。</p>
    </header>

    <div class="settings-surface settings-surface--stack mobile-control-surface">
      <article class="setting-card mobile-control-account-card">
        <div class="subhead">
          <span class="muted subhead-title">服务器账号 <span class="subhead-sub">官方发现与 Relay 必须登录</span></span>
          <span v-if="accountStatus" class="mobile-control-account-state">已登录</span>
        </div>
        <div v-if="accountStatus" class="mobile-control-account-connected">
          <div class="mobile-control-account-copy">
            <strong>{{ accountStatus.username }}</strong>
            <small>{{ accountStatus.baseUrl || accountStatus.serverId }}</small>
            <small v-if="accountIdentity">Node {{ accountIdentity.nodeId }}</small>
          </div>
          <button class="small-btn quiet" type="button" :disabled="accountLoading" @click="logoutAccount">退出账号</button>
        </div>
        <div v-if="accountStatus" class="mobile-control-account-devices">
          <div class="subhead">
            <span class="muted subhead-title">设备与工作环境</span>
            <span class="mobile-control-count">{{ onlineDeviceCount }}/{{ accountDevices.length }} 在线</span>
          </div>
          <div v-if="accountDevices.length" class="mobile-control-account-device-list">
            <div v-for="device in accountDevices" :key="device.nodeId" class="mobile-control-account-device-row">
              <div>
                <strong>{{ device.label }}</strong>
                <small>{{ device.detail }}</small>
              </div>
              <span class="mobile-control-account-device-state" :class="{ offline: !device.online }">
                <i aria-hidden="true" />{{ device.online ? '在线' : '离线' }}
              </span>
            </div>
          </div>
          <p v-else class="mobile-control-empty">这个账号还没有已登记设备。</p>
        </div>
        <form v-else class="mobile-control-account-form" @submit.prevent="submitAccount">
          <label class="mobile-control-field">
            <span>用户名</span>
            <input v-model.trim="accountUsername" type="text" autocomplete="username" minlength="3" maxlength="32" required>
          </label>
          <label class="mobile-control-field">
            <span>密码</span>
            <input v-model="accountPassword" type="password" :autocomplete="accountMode === 'register' ? 'new-password' : 'current-password'" minlength="8" required>
          </label>
          <div class="mobile-control-account-actions">
            <button class="small-btn quiet" type="button" :disabled="accountLoading" @click="accountMode = accountMode === 'login' ? 'register' : 'login'">
              {{ accountMode === 'login' ? '转到注册' : '返回登录' }}
            </button>
            <button class="small-btn primary" type="submit" :disabled="accountLoading || !available">
              {{ accountLoading ? '处理中…' : accountMode === 'register' ? '注册' : '登录' }}
            </button>
          </div>
        </form>
        <p v-if="!available" class="mobile-control-account-note">账号绑定命令将在桌面 Tauri 运行时启用。</p>
      </article>

      <p v-if="error" class="skill-error mobile-control-error" role="alert">{{ error }}</p>

      <button class="mobile-control-more-toggle" type="button" :aria-expanded="moreOpen" @click="moreOpen = !moreOpen">
        <span>更多</span><span aria-hidden="true">{{ moreOpen ? '−' : '+' }}</span>
      </button>

      <template v-if="moreOpen">
      <article class="setting-card mobile-control-toggle-card">
        <div class="mobile-control-toggle-copy">
          <span class="mobile-control-eyebrow">RemoteGateway</span>
          <h2>允许手机控制这台电脑</h2>
          <p v-if="status?.enabled">安全网关已启动；LAN 使用 Noise 加密，公网连接通过自托管 Relay。</p>
          <p v-else>开启后生成设备身份和一次性六位数字配对码。</p>
        </div>
        <button
          class="permission-switch mobile-control-switch"
          type="button"
          :class="{ 'is-on': Boolean(status?.enabled) }"
          :disabled="loading || !available"
          :aria-pressed="status?.enabled ? 'true' : 'false'"
          aria-label="开启手机控制"
          @click="toggleGateway"
        >
          <span class="permission-switch-track" aria-hidden="true"><span /></span>
          <span>{{ status?.enabled ? '已开启' : '已关闭' }}</span>
        </button>
      </article>

      <p v-if="!available" class="mobile-control-notice" role="status">
        手机控制命令将在桌面 Tauri 运行时启用。
      </p>
      <template v-if="status?.enabled">
        <article class="setting-card mobile-control-device-card">
          <div class="subhead">
            <span class="muted subhead-title">本机身份 <span class="subhead-sub">仅用于建立设备信任</span></span>
            <span class="mobile-control-status-dot" aria-label="网关运行中" />
          </div>
          <dl class="mobile-control-meta">
            <div><dt>设备 ID</dt><dd>{{ status.deviceId || '生成中' }}</dd></div>
            <div><dt>网关</dt><dd>{{ status.bindAddr || '局域网' }}<span v-if="status.port">:{{ status.port }}</span></dd></div>
            <div><dt>Relay</dt><dd>{{ status.relayConfigured ? (status.relayConnected ? '已连接' : '重连中') : '未配置' }}</dd></div>
          </dl>
        </article>

        <article class="setting-card mobile-control-pairing-card">
          <div class="subhead">
            <span class="muted subhead-title">配对新设备 <span class="subhead-sub">六位数字码 5 分钟内有效且只能使用一次</span></span>
            <button class="small-btn primary" type="button" :disabled="loading" @click="createPairing">生成配对码</button>
          </div>
          <div v-if="pairing" class="mobile-control-code-layout">
            <div class="mobile-control-code-block" aria-label="当前六位数字配对码">
              <span>当前配对码</span>
              <strong>{{ pairing.code }}</strong>
              <small>在 LamTools 手机端输入此数字</small>
              <button class="text-btn" type="button" @click="copyNumericCode">{{ numericCopyLabel }}</button>
            </div>
            <small class="mobile-control-expires">有效期至 {{ expiresLabel }}</small>
          </div>
          <p v-else class="mobile-control-empty">点击“生成配对码”开始配对。</p>
          <p v-if="!status.relayConfigured" class="mobile-control-warning" role="status">
            当前未配置 Relay，手机无法仅凭数字码发现这台电脑；请先配置远程中转服务。
          </p>
          <p class="mobile-control-phase-note">手机提交数字码后，Relay 只解析连接元数据；真正的配对认证和会话数据仍通过 Noise 加密隧道完成。</p>
        </article>

        <article class="setting-card mobile-control-trusted-card">
          <div class="subhead">
            <span class="muted subhead-title">已配对设备 <span class="subhead-sub">撤销后设备立即失去访问权限</span></span>
            <span class="mobile-control-count">{{ status.trustedDevices?.length || 0 }}</span>
          </div>
          <div v-if="status.trustedDevices?.length" class="mobile-control-trusted-list">
            <div v-for="device in status.trustedDevices" :key="device.deviceId" class="mobile-control-trusted-row">
              <div>
                <strong>{{ device.name || device.deviceId }}</strong>
                <small>{{ device.platform || 'mobile' }} · {{ formatDate(device.lastSeenMs || device.pairedAtMs) }}</small>
              </div>
              <button class="text-btn danger" type="button" :disabled="loading" @click="revoke(device.deviceId)">移除</button>
            </div>
          </div>
          <p v-else class="mobile-control-empty">尚未配对手机。</p>
        </article>
      </template>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

export interface MobileControlTrustedDevice {
  deviceId: string
  name?: string
  platform?: string
  pairedAtMs?: number
  lastSeenMs?: number
}

export interface MobileControlGatewayStatus {
  enabled: boolean
  state?: string
  bindAddr?: string
  port?: number
  deviceId?: string
  publicKey?: string
  trustedDevices?: MobileControlTrustedDevice[]
  activeConnections?: number
  relayConfigured?: boolean
  relayConnected?: boolean
  relayReconnects?: number
  lastError?: string
}

export interface MobileControlPairing {
  pairingId: string
  code: string
  desktopDeviceId: string
  desktopPublicKey: string
  gatewayUrl: string
  relayUrl?: string
  expiresAtMs: number
  protocol: string
  version: number
}

export interface MobileControlAccountStatus {
  baseUrl?: string
  serverId: string
  username: string
  nodeId: string
  accessExpiresAtMs: number
  refreshExpiresAtMs: number
}

export interface MobileControlIdentity {
  nodeId: string
  publicKey: string
}

export interface MobileControlAccountDevice {
  nodeId: string
  label: string
  detail: string
  platform: string
  online: boolean
  current?: boolean
}

export interface MobileControlAccountContext {
  status: MobileControlAccountStatus | null
  devices: MobileControlAccountDevice[]
  loading: boolean
  error: string
}

export interface MobileControlAccountPayload {
  mode: 'login' | 'register'
  baseUrl: string
  username: string
  password: string
}

const props = withDefaults(defineProps<{
  status?: MobileControlGatewayStatus | null
  pairing?: MobileControlPairing | null
  loading?: boolean
  error?: string
  available?: boolean
  accountStatus?: MobileControlAccountStatus | null
  accountIdentity?: MobileControlIdentity | null
  accountLoading?: boolean
  accountDevices?: MobileControlAccountDevice[]
}>(), {
  status: null,
  pairing: null,
  loading: false,
  error: '',
  available: true,
  accountStatus: null,
  accountIdentity: null,
  accountLoading: false,
  accountDevices: () => [],
})

const onlineDeviceCount = computed(() => props.accountDevices.filter((device) => device.online).length)

const emit = defineEmits<{
  'gateway-start': []
  'gateway-stop': []
  'pairing-create': []
  revoke: [deviceId: string]
  'account-submit': [payload: MobileControlAccountPayload]
  'account-logout': []
}>()

const numericCopyLabel = ref('复制数字码')
const accountMode = ref<'login' | 'register'>('login')
const accountUsername = ref('')
const accountPassword = ref('')
const moreOpen = ref(false)
const expiresLabel = computed(() => props.pairing
  ? new Date(props.pairing.expiresAtMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  : '')

function toggleGateway(): void {
  if (props.status?.enabled) emit('gateway-stop')
  else emit('gateway-start')
}

function createPairing(): void { emit('pairing-create') }
function revoke(deviceId: string): void { emit('revoke', deviceId) }
function submitAccount(): void {
  emit('account-submit', {
    mode: accountMode.value,
    baseUrl: '',
    username: accountUsername.value,
    password: accountPassword.value,
  })
  accountPassword.value = ''
}
function logoutAccount(): void { emit('account-logout') }

async function copyNumericCode(): Promise<void> {
  if (!props.pairing?.code || !navigator.clipboard) return
  try {
    await navigator.clipboard.writeText(props.pairing.code)
    numericCopyLabel.value = '已复制'
    window.setTimeout(() => { numericCopyLabel.value = '复制数字码' }, 1600)
  } catch {
    numericCopyLabel.value = '复制失败'
  }
}

function formatDate(value?: number): string {
  if (!value) return '尚未连接'
  return new Date(value).toLocaleString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.mobile-control-panel { --text: var(--theme-main-text); }
.mobile-control-surface { overflow: hidden; }
.mobile-control-account-card { display: grid; gap: var(--space-3); }
.mobile-control-account-state { color: var(--green); font-size: 11px; }
.mobile-control-account-connected { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.mobile-control-account-copy { display: grid; gap: var(--space-1); min-width: 0; }
.mobile-control-account-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mobile-control-account-copy small, .mobile-control-account-note { color: color-mix(in srgb, var(--text) 58%, transparent); font-size: 11px; }
.mobile-control-account-devices { display: grid; gap: var(--space-2); padding-top: var(--space-3); border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); }
.mobile-control-account-device-list { display: grid; gap: var(--space-1); }
.mobile-control-account-device-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); min-height: 42px; padding: var(--space-2); border-radius: var(--radius-sm); }
.mobile-control-account-device-row > div { display: grid; min-width: 0; gap: var(--space-1); }
.mobile-control-account-device-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.mobile-control-account-device-row small { color: color-mix(in srgb, var(--text) 55%, transparent); font-size: 10px; }
.mobile-control-account-device-state { display: inline-flex; flex: 0 0 auto; align-items: center; gap: var(--space-1); color: var(--green); font-size: 11px; }
.mobile-control-account-device-state i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.mobile-control-account-device-state.offline { color: color-mix(in srgb, var(--text) 42%, transparent); }
.mobile-control-account-form { display: grid; gap: var(--space-3); }
.mobile-control-field { display: grid; gap: var(--space-1); min-width: 0; color: color-mix(in srgb, var(--text) 62%, transparent); font-size: 11px; }
.mobile-control-field input { width: 100%; box-sizing: border-box; min-height: 36px; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent); color: var(--theme-composer-text); caret-color: var(--theme-composer-text); padding: 0 var(--space-2); }
.mobile-control-account-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }
.mobile-control-more-toggle { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 36px; padding: 0 var(--space-1); border: 0; border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); background: transparent; color: color-mix(in srgb, var(--text) 65%, transparent); font: inherit; font-size: 12px; cursor: pointer; }
.mobile-control-toggle-card { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); }
.mobile-control-toggle-copy { min-width: 0; }
.mobile-control-toggle-copy h2 { margin: 0 0 var(--space-1); font-size: 16px; }
.mobile-control-toggle-copy p, .mobile-control-empty, .mobile-control-notice { margin: 0; color: color-mix(in srgb, var(--text) 62%, transparent); font-size: 12px; line-height: 1.5; }
.mobile-control-eyebrow { display: block; margin-bottom: var(--space-1); color: color-mix(in srgb, var(--blue) 76%, var(--text)); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
.mobile-control-switch { flex: 0 0 auto; }
.mobile-control-notice { padding: var(--space-3) var(--space-4); border: 1px dashed color-mix(in srgb, var(--text) 16%, transparent); }
.mobile-control-error { margin: 0; }
.mobile-control-status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 4px color-mix(in srgb, var(--green) 16%, transparent); }
.mobile-control-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); margin: 0; }
.mobile-control-meta div { display: grid; gap: var(--space-1); min-width: 0; }
.mobile-control-meta dt { color: color-mix(in srgb, var(--text) 52%, transparent); font-size: 11px; }
.mobile-control-meta dd { margin: 0; overflow: hidden; color: var(--text); font-family: var(--font-mono); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.mobile-control-code-layout { display: grid; justify-items: start; gap: var(--space-2); padding-top: var(--space-3); }
.mobile-control-code-block { display: grid; justify-items: center; gap: var(--space-1); min-width: min(100%, 280px); padding: var(--space-4) var(--space-5); border: 1px solid color-mix(in srgb, var(--blue) 28%, transparent); border-radius: var(--radius); background: color-mix(in srgb, var(--blue) 7%, var(--theme-main-background)); }
.mobile-control-code-block span, .mobile-control-code-block small, .mobile-control-expires { color: color-mix(in srgb, var(--text) 58%, transparent); font-size: 11px; }
.mobile-control-code-block strong { color: var(--blue); font-family: var(--font-mono); font-size: 36px; letter-spacing: .18em; line-height: 1.15; text-indent: .18em; }
.mobile-control-code-block .text-btn { min-height: 28px; padding: 0 var(--space-2); }
.mobile-control-warning { margin: var(--space-3) 0 0; color: var(--orange, #e7a65b); font-size: 11px; line-height: 1.5; }
.mobile-control-phase-note { margin: var(--space-2) 0 0; color: color-mix(in srgb, var(--text) 55%, transparent); font-size: 11px; line-height: 1.5; }
.mobile-control-trusted-list { display: grid; }
.mobile-control-trusted-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) 0; border-top: 1px solid color-mix(in srgb, var(--text) 10%, transparent); }
.mobile-control-trusted-row:first-child { border-top: 0; }
.mobile-control-trusted-row > div { display: grid; gap: var(--space-1); min-width: 0; }
.mobile-control-trusted-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mobile-control-trusted-row small { color: color-mix(in srgb, var(--text) 54%, transparent); font-size: 11px; }
.mobile-control-count { min-width: 22px; color: color-mix(in srgb, var(--text) 62%, transparent); font-family: var(--font-mono); font-size: 12px; text-align: right; }
@media (max-width: 760px) {
  .mobile-control-toggle-card { align-items: flex-start; flex-direction: column; }
  .mobile-control-code-block { width: 100%; box-sizing: border-box; }
}
@media (prefers-reduced-motion: reduce) { .mobile-control-status-dot { box-shadow: none; } }
</style>
