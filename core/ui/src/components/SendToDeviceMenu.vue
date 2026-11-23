<template>
  <div class="send-menu" data-send-to-device @click.stop>
    <header class="send-menu__head">
      <span class="send-menu__title">{{ t('发送到设备') }}</span>
      <button class="send-menu__close" type="button" :aria-label="t('关闭')" @click="emit('close')">×</button>
    </header>
    <p class="send-menu__file" :title="props.path">{{ displayName }}</p>

    <p v-if="error" class="send-menu__error" role="alert">{{ error }}</p>
    <p v-else-if="loading" class="send-menu__note">{{ t('正在读取设备…') }}</p>

    <ul v-else-if="rows.length" class="send-menu__list">
      <li v-for="row in rows" :key="row.target.id" class="send-menu__item">
        <button
          class="send-menu__device"
          type="button"
          :disabled="Boolean(row.reason) || sending === row.target.id"
          :title="row.reason || row.warning || ''"
          :data-send-device="row.target.id"
          @click="send(row.target)"
        >
          <span class="send-menu__name">{{ row.target.name }}</span>
          <span class="send-menu__meta">{{ targetSubtitle(row.target) }}</span>
          <!-- 不可发时把原因写在按钮里：不是灰掉就完事。 -->
          <span v-if="row.reason" class="send-menu__reason">{{ row.reason }}</span>
          <span v-else-if="row.warning" class="send-menu__warning">{{ row.warning }}</span>
          <span v-else-if="sending === row.target.id" class="send-menu__meta">{{ t('发送中：{0}', { 0: displayName }) }}</span>
        </button>
      </li>
    </ul>
    <p v-else class="send-menu__note">{{ t('这台电脑上还没有配对的设备。先在「设备连接」里配对。') }}</p>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onMounted, ref } from 'vue'
import { sendEligibility, mergeTransferTargets, targetSubtitle, type TransferTarget } from '@/transfer/send.ts'
import { trackSendSource, sendFileToDevice, ticketForDevice } from '@/transfer/dispatch.ts'
import { readDevices, type PairedDevice } from '@/app/remoteSession.ts'

/**
 * 文件 → 已信任设备 的发送入口。
 *
 * user:“发送入口：文件树、资料库、预览器里对文件加「发送到设备」——列出已信任设备（含在线
 * 状态与直连/中继），选中后开始传输；对端离线/未配对给可读原因，不要静默失败”+
 * (菜单里每一行都由「可信名单 + 在线名册 + 本机是否有票」三件事合成：能发的直接发，
 * 不能发的当场写清为什么，不让用户点一个灰按钮猜原因)。
 */
const props = defineProps<{
  /** 本机源文件的绝对路径。 */
  path: string
  /** 显示/对端保存用的文件名（可空，宿主按路径取名）。 */
  name?: string
  /** 字节数：超上限时提前拦住（未知则不做上限判断）。 */
  size?: number
  /** 宿主命令通道；单测/展厅里注入替身。 */
  invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>
  /** user:“交互测试”+(展厅不读取实际配对票据，也不登记真实发送记录)。 */
  previewServices?: { devices: () => PairedDevice[]; sent: typeof trackSendSource }
}>()

const emit = defineEmits<{
  (event: 'sent', payload: { transferId: string; deviceId: string; path: string; name: string }): void
  (event: 'close'): void
}>()

interface Row {
  target: TransferTarget
  ticket: string
  reason: string
  warning: string
}

const loading = ref(true)
const error = ref('')
const sending = ref('')
const rows = ref<Row[]>([])
const paired = ref<PairedDevice[]>([])

const displayName = computed(() => {
  const explicit = (props.name || '').trim()
  if (explicit) return explicit
  const fromPath = props.path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || ''
  return fromPath || props.path
})

function host(): ((command: string, args?: Record<string, unknown>) => Promise<unknown>) | null {
  if (props.invoke) return props.invoke
  const bridge = (window as unknown as {
    __TAURI_INTERNALS__?: { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> }
  }).__TAURI_INTERNALS__
  return bridge ? bridge.invoke.bind(bridge) : null
}

/**
 * 读三份事实：可信名单（宿主）、在线名册（宿主状态）、本机票据（界面记住的配对）。
 *
 * user:“列出已信任设备（含在线状态与直连/中继）”+(可信名单管「谁允许收」，在线名册管
 * 「谁现在连得上」，票据管「本机拨得动谁」；三份缺一份都会变成「点了没反应」)。
 */
async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  const invoke = host()
  if (!invoke) {
    // 没有宿主通道（浏览器预览、纯网页）：如实说，不假装能发。
    loading.value = false
    error.value = t('发送需要在桌面应用里使用。')
    return
  }
  try {
    paired.value = (props.previewServices?.devices ?? readDevices)()
    const trusted = (await invoke('p2p_devices')) as { devices?: Array<{ id?: unknown; name?: unknown }> } | null
    const status = (await invoke('p2p_status')) as
      | { devices?: Array<{ id?: unknown; name?: unknown; path?: unknown }> }
      | null
    const targets = mergeTransferTargets(
      Array.isArray(trusted?.devices) ? trusted.devices : [],
      Array.isArray(status?.devices) ? status.devices : [],
      (id) => Boolean(ticketForDevice(paired.value, id)),
    )
    const payload = { path: props.path, size: props.size || 0 }
    rows.value = targets.map((target) => {
      const ticket = ticketForDevice(paired.value, target.id)
      const verdict = sendEligibility(target, payload)
      return {
        target,
        ticket,
        reason: verdict.allowed ? '' : verdict.reason,
        warning: verdict.allowed ? verdict.warning : '',
      }
    })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

/** 选中即开始传输；宿主起来的发送进程会把进度写进同一个名册。 */
async function send(target: TransferTarget): Promise<void> {
  const invoke = host()
  const row = rows.value.find((item) => item.target.id === target.id)
  if (!invoke || !row || row.reason) return
  sending.value = target.id
  error.value = ''
  try {
    const sent = await sendFileToDevice(invoke, { path: props.path, name: displayName.value, ticket: row.ticket })
    const recordSource = props.previewServices?.sent ?? trackSendSource
    recordSource(sent.transferId, props.path)
    emit('sent', { transferId: sent.transferId, deviceId: target.id, path: props.path, name: displayName.value })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    sending.value = ''
  }
}

onMounted(() => {
  void load()
})

defineExpose({ reload: load })
</script>

<style scoped>
.send-menu {
  display: grid;
  gap: 8px;
  min-width: 240px;
  max-width: 320px;
  padding: 10px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius-md, 12px);
  background: var(--theme-surface, Canvas);
  color: inherit;
  box-shadow: 0 10px 28px color-mix(in srgb, #000 22%, transparent);
}

.send-menu__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.send-menu__title {
  font-size: 12px;
  font-weight: 650;
}

.send-menu__close {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: inherit;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.6;
}

.send-menu__file {
  margin: 0;
  font-size: 11px;
  opacity: 0.55;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.send-menu__error {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--red, #e5484d);
}

.send-menu__note {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  opacity: 0.55;
}

.send-menu__list {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.send-menu__device {
  display: grid;
  gap: 2px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.send-menu__device:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.send-menu__device:disabled {
  cursor: default;
  opacity: 0.55;
}

.send-menu__name {
  font-size: 12px;
}

.send-menu__meta {
  font-size: 10px;
  opacity: 0.6;
}

.send-menu__reason {
  font-size: 10px;
  line-height: 1.5;
  color: var(--red, #e5484d);
}

.send-menu__warning {
  font-size: 10px;
  line-height: 1.5;
  color: var(--amber, #d4880f);
}
</style>
