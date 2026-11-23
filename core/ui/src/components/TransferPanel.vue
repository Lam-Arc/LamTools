<template>
  <!-- user:“这个组内的 UI 设计与风格”+(互传区域与设备页的配对区域共用实色内容面板)。 -->
  <section class="transfer-panel sunday-page-panel" data-transfer-panel>
    <header class="transfer-panel__head">
      <h3 class="transfer-panel__title">{{ t('文件互传') }}</h3>
      <button
        class="transfer-panel__refresh"
        type="button"
        :disabled="book.loading.value"
        data-transfer-refresh
        @click="book.refresh()"
      >
        {{ t('刷新') }}
      </button>
    </header>

    <p v-if="book.error.value" class="sunday-page-status sunday-page-status--error" role="alert">{{ book.error.value }}</p>

    <!-- 传输面板：方向、文件名、进度、状态，可取消、可重试、可定位。 -->
    <ul v-if="book.transfers.value.length" class="transfer-list" data-transfer-list>
      <li
        v-for="row in book.transfers.value"
        :key="row.id"
        class="transfer-row"
        :class="[`is-${row.state}`, { 'is-animating': row.active && book.animating.value }]"
        :data-transfer-id="row.id"
      >
        <div class="transfer-row__head">
          <span class="transfer-row__dir" :class="`is-${row.direction}`">{{ transferDirectionLabel(row.direction) }}</span>
          <span class="transfer-row__name" :title="row.name">{{ row.name }}</span>
          <span class="transfer-row__state">{{ transferStateLabel(row.state) }}</span>
        </div>

        <!-- user:“统一与去重”+(用共享进度条保留文件传输的尺寸与状态动效)。 -->
        <SundayProgress class="transfer-row__bar" :label="row.name" :value="row.percent" />

        <div class="transfer-row__meta">
          <span class="transfer-row__bytes">{{ progressText(row) }}</span>
          <span class="transfer-row__percent">{{ row.percent }}%</span>
        </div>

        <!-- 失败原因：错误码一对一翻成中文，未知码带上传输层原文。 -->
        <p v-if="row.code || row.message" class="transfer-row__reason" :class="`is-${transferErrorTone(row.code)}`">
          {{ transferErrorText(row.code, row.message) }}
        </p>

        <div class="transfer-row__actions">
          <button
            v-if="row.active"
            class="transfer-row__button"
            type="button"
            :data-transfer-cancel="row.id"
            @click="book.cancel(row.id)"
          >
            {{ t('取消') }}
          </button>
          <button
            v-if="row.retryable"
            class="transfer-row__button"
            type="button"
            :disabled="!retrySource(row)"
            :title="retrySource(row) ? '' : t('这次发送不是本窗口发起的，重新从文件那里再发一次。')"
            :data-transfer-retry="row.id"
            @click="onRetry(row)"
          >
            {{ t('重试') }}
          </button>
          <button
            v-if="row.direction === 'receive' && row.state === 'completed' && row.path"
            class="transfer-row__button"
            type="button"
            :data-transfer-reveal="row.id"
            @click="book.reveal(row.path)"
          >
            {{ t('打开所在文件夹') }}
          </button>
        </div>
      </li>
    </ul>
    <p v-else-if="!book.loading.value" class="transfer-panel__empty">{{ t('还没有传输记录。在文件上点「发送到设备」就能开始。') }}</p>

    <!-- 接收列表：预览走统一链路，定位走系统文件夹。 -->
    <div class="transfer-received" data-transfer-received>
      <h4 class="transfer-received__title">{{ t('收到的文件') }}</h4>
      <ul v-if="book.received.value.length" class="received-list">
        <li v-for="row in book.received.value" :key="row.path" class="received-row" :data-received-path="row.path">
          <div class="received-row__body">
            <span class="received-row__name" :title="row.path">
              {{ receivedTitle(row) }}
              <span v-if="book.fresh(row)" class="received-row__badge" data-received-fresh>{{ t('新') }}</span>
            </span>
            <span class="received-row__meta">{{ receivedMeta(row) }}</span>
            <span v-if="!receivedActions(row).canPreview" class="received-row__hint">
              {{ receivedActions(row).previewReason }}
            </span>
          </div>
          <div class="received-row__actions">
            <button
              class="transfer-row__button"
              type="button"
              :disabled="!receivedActions(row).canPreview"
              :title="receivedActions(row).canPreview ? '' : receivedActions(row).previewReason"
              :data-received-preview="row.path"
              @click="preview(row)"
            >
              {{ t('预览') }}
            </button>
            <button
              class="transfer-row__button"
              type="button"
              :disabled="!receivedActions(row).canReveal"
              :data-received-reveal="row.path"
              @click="book.reveal(row.path)"
            >
              {{ t('打开所在文件夹') }}
            </button>
          </div>
        </li>
      </ul>
      <p v-else class="transfer-panel__empty">{{ t('还没收到过文件。对端发过来的文件会出现在这里。') }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'
import SundayProgress from '@/components/SundayProgress.vue'

import { openInLightbox } from '@/preview/usePreviewLightbox'
import {
  progressText,
  transferDirectionLabel,
  transferStateLabel,
  type ReceivedRow,
  type TransferRow,
} from '@/transfer/shape'
import { transferErrorText, transferErrorTone } from '@/transfer/codes'
import { receivedActions, receivedMeta, receivedPreviewTarget, receivedTitle } from '@/transfer/received'
import { windowSendSources } from '@/transfer/dispatch'
import { useTransferBookLifecycle } from '@/transfer/useTransferBook'

/**
 * 文件互传面板。
 *
 * user:“传输面板：在「远程连接」面板或文件屏里列出 transfers[]（方向、文件名、进度、状态），
 * 支持取消；失败可重试；完成后可「打开所在文件夹」”+
 * user:“接收列表：列出 received[]，每条可「预览」与「打开所在文件夹」；新收到的文件要有
 * 可见提示”+(一块面板同时承担「正在传」与「已经收到」两件事：进度靠宿主推送，动作只有
 * 取消/重试/预览/定位四种，每一种不可用时都写明原因，不做点了没反应的按钮)。
 */
const props = defineProps<{
  /** 宿主命令通道；隔离预览或单测里注入替身。 */
  invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>
  /**
   * 发送意图登记：本窗口发出去的行才能重试（源文件路径只有发起方知道）。
   * 键是传输 id，值是本机源文件路径。
   */
  sendSources?: Record<string, string>
  /** 注入「现在」（Unix 秒），用于「新收到的文件」提示；单测用。 */
  now?: () => number
  /** user:“交互测试”+(展厅的预览和事件来源与实际宿主隔离)。 */
  previewServices?: { open: (row: ReceivedRow) => void }
}>()

const emit = defineEmits<{
  /** 重试一次发送：由发起方重新走「发送到设备」，这里只负责请求。 */
  (event: 'retry', payload: { path: string; name: string }): void
}>()

const book = useTransferBookLifecycle({ invoke: props.invoke, now: props.now, listenToHost: !props.previewServices })

function retrySource(row: TransferRow): string {
  // 宿主的 source 最权威；没有就依次退回本窗口登记表与父级传入的映射。
  return row.source || windowSendSources()[row.id] || props.sendSources?.[row.id] || ''
}

function onRetry(row: TransferRow): void {
  const path = retrySource(row)
  if (!path) return
  emit('retry', { path, name: row.name })
}

/** 预览：一律走 `preview/` 的统一链路（灯箱），不在这里另写一套按扩展名分派。 */
function preview(row: ReceivedRow): void {
  const actions = receivedActions(row)
  if (!actions.canPreview) return
  if (props.previewServices) props.previewServices.open(row)
  else openInLightbox(receivedPreviewTarget(row))
}
</script>

<style scoped>
.transfer-panel {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-3);
}

.transfer-panel__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.transfer-panel__title {
  margin: 0;
  font-size: 13px;
  font-weight: 650;
}

.transfer-panel__refresh {
  margin-left: auto;
  padding: 4px 10px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.transfer-panel__refresh:disabled {
  opacity: 0.4;
  cursor: default;
}



.transfer-panel__empty {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  opacity: 0.55;
}

.transfer-list,
.received-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.transfer-row {
  display: grid;
  gap: 6px;
  padding: 10px;
  border-radius: var(--radius-sm, 8px);
  background: color-mix(in srgb, var(--theme-main-text) 4%, transparent);
}

.transfer-row__head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  min-width: 0;
}

.transfer-row__dir {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 11px;
  background: color-mix(in srgb, var(--theme-main-text) 10%, transparent);
}

.transfer-row__dir.is-receive {
  background: color-mix(in srgb, var(--green, #3ecf8e) 20%, transparent);
}

.transfer-row__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.transfer-row__state {
  margin-left: auto;
  flex: none;
  opacity: 0.6;
  font-size: 11px;
}

.transfer-row__bar {
  height: 5px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text) 12%, transparent);
}

.transfer-row__bar :deep(.sunday-progress__fill) {
  background: color-mix(in srgb, var(--theme-main-text) 55%, transparent);
  transition: width 0.25s linear;
}

/* 只在真的有在传、且界面可见时才跑动画：后台不留空转。 */
.transfer-row.is-animating .transfer-row__bar :deep(.sunday-progress__fill) {
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--theme-main-text) 40%, transparent),
    color-mix(in srgb, var(--theme-main-text) 70%, transparent),
    color-mix(in srgb, var(--theme-main-text) 40%, transparent)
  );
  background-size: 200% 100%;
  animation: transfer-flow 1.6s linear infinite;
}

.transfer-row.is-failed .transfer-row__bar :deep(.sunday-progress__fill) {
  background: color-mix(in srgb, var(--red, #e5484d) 60%, transparent);
}

.transfer-row.is-cancelled .transfer-row__bar :deep(.sunday-progress__fill),
.transfer-row.is-completed .transfer-row__bar :deep(.sunday-progress__fill) {
  background: color-mix(in srgb, var(--green, #3ecf8e) 55%, transparent);
}

@keyframes transfer-flow {
  from { background-position: 100% 0; }
  to { background-position: -100% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .transfer-row__bar :deep(.sunday-progress__fill) {
    transition: none;
  }

  .transfer-row.is-animating .transfer-row__bar :deep(.sunday-progress__fill) {
    animation: none;
  }
}

.transfer-row__meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  opacity: 0.65;
  font-variant-numeric: tabular-nums;
}

.transfer-row__percent {
  margin-left: auto;
}

.transfer-row__reason {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
}

.transfer-row__reason.is-error {
  color: var(--red, #e5484d);
}

.transfer-row__reason.is-warn {
  color: var(--amber, #d4880f);
}

.transfer-row__reason.is-info {
  opacity: 0.6;
}

.transfer-row__actions,
.received-row__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.transfer-row__button {
  padding: 3px 10px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.transfer-row__button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) 7%, transparent);
}

.transfer-row__button:disabled {
  opacity: 0.35;
  cursor: default;
}

.transfer-received {
  display: grid;
  gap: 8px;
}

.transfer-received__title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  opacity: 0.7;
}

.received-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-sm, 8px);
  background: color-mix(in srgb, var(--theme-main-text) 4%, transparent);
}

.received-row__body {
  display: grid;
  gap: 2px;
  min-width: 0;
  font-size: 12px;
}

.received-row__name {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.received-row__badge {
  flex: none;
  padding: 0 5px;
  border-radius: 999px;
  font-size: 10px;
  background: color-mix(in srgb, var(--green, #3ecf8e) 26%, transparent);
}

.received-row__meta {
  font-size: 11px;
  opacity: 0.6;
}

.received-row__hint {
  font-size: 11px;
  line-height: 1.5;
  opacity: 0.5;
}

.received-row__actions {
  margin-left: auto;
  flex: none;
}
</style>
