<template>
  <div class="mobile-diagnostics-overlay" role="presentation" @click.self="emit('close')">
    <section
      class="mobile-diagnostics-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mobile-diagnostics-title"
    >
      <header class="mobile-diagnostics-panel__header">
        <div>
          <p class="mobile-diagnostics-panel__eyebrow">移动端</p>
          <h2 id="mobile-diagnostics-title">诊断日志</h2>
        </div>
        <button class="mobile-diagnostics-panel__close" type="button" aria-label="关闭诊断日志" @click="emit('close')">
          <X :size="18" aria-hidden="true" />
        </button>
      </header>

      <div class="mobile-diagnostics-panel__content">
        <p class="mobile-diagnostics-panel__summary">
          当前保留 <strong>{{ entryCount }}</strong> / {{ retentionLimit }} 条记录。采集记录只存在于本次应用运行的内存中，页面或应用重新载入后清空。
        </p>
        <div class="mobile-diagnostics-panel__privacy">
          <ShieldCheck :size="18" aria-hidden="true" />
          <p>导出包含时间、传输阶段、状态和数据量。不会包含对话或文件内容、密钥、地址、设备 ID、请求 ID、运行 ID 或原始错误文本。</p>
        </div>
        <p class="mobile-diagnostics-panel__retention">
          记录来自 LamTools 网络传输和原生执行阶段；不会读取 Android 系统日志（logcat）。
        </p>
        <p class="mobile-diagnostics-panel__retention">
          Android 分享会把文件暂存在应用缓存中供分享目标读取。你选择的目标应用或保存位置决定导出副本的去向；下次导出会覆盖缓存临时副本，系统清理应用缓存时也会删除它。
        </p>
        <p v-if="message" class="mobile-diagnostics-panel__message" role="status" aria-live="polite">{{ message }}</p>
      </div>

      <footer class="mobile-diagnostics-panel__actions">
        <button class="mobile-diagnostics-panel__clear" type="button" :disabled="!entryCount || busy" @click="emit('clear')">
          清除记录
        </button>
        <button class="mobile-diagnostics-panel__export" type="button" :disabled="busy" @click="emit('export')">
          <LoaderCircle v-if="busy" class="is-spinning" :size="16" aria-hidden="true" />
          <Share2 v-else :size="16" aria-hidden="true" />
          <span>{{ busy ? '正在准备' : '分享诊断日志' }}</span>
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { LoaderCircle, Share2, ShieldCheck, X } from 'lucide-vue-next'
import { MOBILE_DIAGNOSTIC_RETENTION_LIMIT } from './MobileDiagnostics'

defineProps<{
  entryCount: number
  busy: boolean
  message: string
}>()

const emit = defineEmits<{
  close: []
  clear: []
  export: []
}>()

const retentionLimit = MOBILE_DIAGNOSTIC_RETENTION_LIMIT
</script>

<style>
.mobile-diagnostics-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  box-sizing: border-box;
  padding: max(var(--space-4), env(safe-area-inset-top, 0px)) var(--space-4) max(var(--space-4), env(safe-area-inset-bottom, 0px));
  overflow: auto;
  background: color-mix(in srgb, var(--theme-backdrop-text) 16%, transparent);
  backdrop-filter: blur(5px);
}

.mobile-diagnostics-panel {
  width: min(100%, 420px);
  box-sizing: border-box;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius-lg);
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  box-shadow: var(--shadow-xl);
}

.mobile-diagnostics-panel__header,
.mobile-diagnostics-panel__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4);
}

.mobile-diagnostics-panel__header {
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
}

.mobile-diagnostics-panel__eyebrow {
  margin: 0 0 var(--space-1);
  color: color-mix(in srgb, var(--theme-main-text) 56%, transparent);
  font-size: 11px;
  font-weight: 650;
}

.mobile-diagnostics-panel h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 680;
}

.mobile-diagnostics-panel__close {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.mobile-diagnostics-panel__close:hover,
.mobile-diagnostics-panel__clear:hover {
  background: color-mix(in srgb, var(--theme-main-text) 8%, transparent);
}

.mobile-diagnostics-panel__content {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
}

.mobile-diagnostics-panel__summary,
.mobile-diagnostics-panel__retention,
.mobile-diagnostics-panel__privacy p {
  margin: 0;
  color: color-mix(in srgb, var(--theme-main-text) 72%, transparent);
  font-size: 13px;
  line-height: 1.55;
}

.mobile-diagnostics-panel__summary strong {
  color: var(--theme-main-text);
  font-variant-numeric: tabular-nums;
}

.mobile-diagnostics-panel__privacy {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--theme-main-text) 4%, transparent);
}

.mobile-diagnostics-panel__privacy svg {
  flex: none;
  margin-top: 1px;
  color: var(--green, #54a881);
}

.mobile-diagnostics-panel__message {
  margin: 0;
  color: var(--theme-main-text);
  font-size: 12px;
  line-height: 1.5;
}

.mobile-diagnostics-panel__actions {
  justify-content: flex-end;
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
}

.mobile-diagnostics-panel__clear,
.mobile-diagnostics-panel__export {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: var(--radius-sm);
  color: var(--theme-main-text);
  font: inherit;
  font-size: 13px;
  font-weight: 620;
  cursor: pointer;
}

.mobile-diagnostics-panel__clear {
  background: transparent;
}

.mobile-diagnostics-panel__export {
  border-color: var(--theme-control-border, color-mix(in srgb, var(--theme-main-text) 16%, transparent));
  background: var(--theme-control-background);
  color: var(--theme-control-text);
}

.mobile-diagnostics-panel button:disabled {
  cursor: default;
  opacity: .5;
}

.mobile-diagnostics-panel button:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--theme-main-text) 72%, transparent);
  outline-offset: 2px;
}

@keyframes mobile-diagnostics-spin {
  to { transform: rotate(360deg); }
}

.mobile-diagnostics-panel .is-spinning {
  animation: mobile-diagnostics-spin 1s linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  .mobile-diagnostics-overlay { backdrop-filter: none; }
  .mobile-diagnostics-panel .is-spinning { animation: none; }
}
</style>
