<template>
  <div class="full-area-column full-area-surface account-view" :style="settingsThemeStyle">
        <header class="account-head">
          <button class="account-back" type="button" aria-label="返回会话" title="返回会话" @click="$emit('close')">
            <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <span class="account-head-title">账号</span>
          <span v-if="accountStatus" class="account-head-state">已登录</span>
          <span v-else class="account-head-state is-off">未登录</span>
          <button
            v-if="onRefresh"
            class="account-action"
            type="button"
            :disabled="loading"
            @click="onRefresh()"
          >
            {{ loading ? '刷新中…' : '刷新' }}
          </button>
        </header>

        <main class="account-body">
          <p v-if="error" class="account-error" role="alert">{{ error }}</p>

          <section class="account-section">
            <div class="account-row">
              <span class="account-row-label">当前账号</span>
              <span class="account-row-value">{{ accountStatus?.username || '未登录' }}</span>
            </div>
            <div v-if="accountStatus" class="account-row">
              <span class="account-row-label">节点</span>
              <span class="account-row-value is-mono">{{ accountStatus.nodeId }}</span>
            </div>
            <div v-if="accountStatus?.baseUrl" class="account-row">
              <span class="account-row-label">服务器</span>
              <span class="account-row-value is-mono">{{ accountStatus.baseUrl }}</span>
            </div>
            <div class="account-actions">
              <button
                v-if="accountStatus"
                class="account-btn"
                type="button"
                :disabled="loading"
                @click="onLogout()"
              >
                退出账号
              </button>
              <button v-else class="account-btn is-primary" type="button" @click="onOpenSettings()">
                去登录
              </button>
            </div>
          </section>

          <section class="account-section">
            <div class="account-section-title">
              设备
              <span class="account-section-note">{{ devices.length ? `${onlineCount}/${devices.length} 在线` : '暂无' }}</span>
            </div>
            <ul v-if="devices.length" class="account-devices">
              <li v-for="device in devices" :key="device.nodeId" class="account-device">
                <span class="account-device-dot" :class="{ online: device.online }" aria-hidden="true"></span>
                <span class="account-device-label">{{ device.label }}</span>
                <span v-if="device.current" class="account-device-badge">本机</span>
                <span class="account-device-detail">{{ device.detail }}</span>
              </li>
            </ul>
            <p v-else class="account-empty">登录后在手机上配对，这里会列出已配对的设备。</p>
          </section>

          <section class="account-section">
            <div class="account-section-title">
              方案传输
              <span class="account-section-note">待接入</span>
            </div>
            <p class="account-empty">
              手机做方案，电脑开工：方案先存在手机上，桌面端导入后即可核对并开始执行。
              自动送达（账号直传）尚未接入，先用导出／导入这一步。
            </p>
          </section>
        </main>

        <footer class="account-foot">
          <button class="account-link" type="button" @click="onOpenSettings()">
            打开完整设置（账号与设备）
          </button>
        </footer>
  </div>
</template>

<script setup lang="ts">
/**
 * AccountShell — 账号的独立界面。
 *
 * 用户共识：账号单独一个界面，内容先保持很少，以后再添。所以这里只放
 * 「现在是谁 / 有哪些设备 / 方案传输会不会用到账号」三件事：
 * - 登录、注册、配对、撤销设备仍然由完整设置里的手机控制面板负责（不复制表单）；
 * - 方案传输尚未接入，这里明确写成“待接入”，不摆一个按不动的按钮。
 */
import { computed, ref } from 'vue'
import { ArrowLeft } from 'lucide-vue-next'
import { gradientFromStops, relativeLuminance, type ThemeData } from '../helpers/theme'
import type {
  MobileControlAccountDevice,
  MobileControlAccountStatus,
} from './MobileControlPanel.vue'

const props = defineProps<{
  accountStatus?: MobileControlAccountStatus | null
  devices?: MobileControlAccountDevice[]
  loading?: boolean
  error?: string
  theme?: ThemeData | null
  onLogout: () => void
  onOpenSettings: () => void
  onRefresh?: () => void
}>()

const emit = defineEmits<{ close: [] }>()


const devices = computed(() => props.devices || [])
const onlineCount = computed(() => devices.value.filter((device) => device.online).length)


const settingsThemeStyle = computed(() => {
  if (!props.theme) return {}
  const theme = props.theme
  const lightMain = relativeLuminance(theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': gradientFromStops(theme.backdropAngle, theme.backdropStops, 1),
    '--settings-backdrop-text': theme.backdropText,
    '--settings-main-background': gradientFromStops(theme.mainAngle, theme.mainStops, theme.mainOpacity),
    '--settings-main-text': theme.mainText,
    '--settings-main-solid': theme.mainStops[0]?.color || '#111111',
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': theme.mainText,
    '--settings-control-background': gradientFromStops(theme.controlAngle, theme.controlStops, theme.controlOpacity),
    '--settings-control-text': theme.controlText,
    '--settings-control-solid': theme.controlStops[0]?.color || '#3a3834',
    ...(lightMain
      ? {
          '--settings-panel-2': '#f0efeb',
          '--settings-line': '#d4d0cc',
          '--settings-muted': '#8a8580',
        }
      : {}),
  } as Record<string, string>
})
</script>

<style scoped>
.account-card {
  display: flex;
  flex-direction: column;
  width: min(520px, 100%);
  max-height: min(600px, calc(100vh - 160px));
}

.account-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
  padding: var(--space-3);
  color: var(--settings-main-text, #fff);
}

.account-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 68%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.account-back:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.account-action {
  margin-left: auto;
  min-height: 28px;
  padding: 5px var(--space-3);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 78%, transparent);
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.account-action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.account-action:disabled { opacity: .45; cursor: default; }

/* 桌面：标题与返回键由顶部条承担，这里只留登录状态。 */
@media (min-width: 641px) {
  .account-back,
  .account-head-title {
    display: none;
  }
}

.account-head-title {
  font-size: 15px;
  font-weight: 650;
}

.account-head-state {
  border-radius: var(--radius-sm);
  padding: 1px var(--space-1);
  background: color-mix(in srgb, var(--green) 18%, transparent);
  color: var(--settings-muted, #a7a29b);
  font-size: 10px;
}

.account-head-state.is-off {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
}

.account-icon-btn {
  display: inline-flex;
  border: none;
  border-radius: var(--radius-sm);
  padding: 2px;
  background: none;
  color: var(--settings-muted, #a7a29b);
  cursor: pointer;
}

.account-icon-btn:first-of-type {
  margin-left: auto;
}

.account-icon-btn:hover {
  color: var(--settings-card-text, var(--text));
}

.account-icon-btn:disabled {
  opacity: .45;
}

.account-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  --text: var(--settings-card-text, var(--settings-main-text, #fff));
  color: var(--text);
}

.account-section {
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
  padding: var(--space-3);
}

.account-section:last-child {
  border-bottom: none;
}

.account-section-title {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  color: var(--text);
  font-size: 12px;
  font-weight: 650;
}

.account-section-note {
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 11px;
  font-weight: 400;
}

.account-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: var(--space-2);
  align-items: baseline;
  padding: 3px 0;
}

.account-row-label {
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 11px;
}

.account-row-value {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-row-value.is-mono {
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.account-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.account-btn {
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  padding: 5px var(--space-2);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.account-btn:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.account-btn.is-primary {
  background: var(--settings-control-background, #343331);
  color: var(--settings-control-text, var(--text));
}

.account-btn:disabled {
  opacity: .45;
}

.account-devices {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-1);
}

.account-device {
  display: grid;
  grid-template-columns: 6px auto auto minmax(0, 1fr);
  gap: var(--space-2);
  align-items: center;
  font-size: 12px;
}

.account-device-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--text) 30%, transparent);
}

.account-device-dot.online {
  background: var(--green);
}

.account-device-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-device-badge {
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1);
  background: color-mix(in srgb, var(--text) 8%, transparent);
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 10px;
}

.account-device-detail {
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 11px;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-empty {
  margin: 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
  line-height: 1.6;
}

.account-error {
  margin: 0;
  padding: var(--space-2) var(--space-3) 0;
  color: var(--red);
  font-size: 12px;
}

.account-foot {
  flex-shrink: 0;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
  padding: var(--space-2) var(--space-3);
}

.account-link {
  border: none;
  padding: 0;
  background: none;
  color: color-mix(in srgb, var(--settings-main-text, #fff) 65%, transparent);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.account-link:hover {
  color: var(--settings-main-text, #fff);
}
</style>
