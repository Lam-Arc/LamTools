<template>
  <div class="sync-overlay" role="presentation" @pointerdown.self="requestClose">
    <section class="sync-panel" role="dialog" aria-modal="true" aria-labelledby="mobile-sync-title" tabindex="-1" @keydown.esc.stop.prevent="requestClose">
      <header>
        <div>
          <p class="sync-kicker">通信共享</p>
          <h2 id="mobile-sync-title">同步项目</h2>
        </div>
        <button type="button" aria-label="关闭同步页面" :disabled="busy" @click="requestClose">×</button>
      </header>

      <div class="sync-body">
        <section>
          <h3>1. 选择设备</h3>
          <div class="sync-device-list">
            <button
              v-for="device in devices"
              :key="device.id"
              type="button"
              class="sync-device"
              :class="{ selected: device.id === selectedDeviceId }"
              :aria-pressed="device.id === selectedDeviceId"
              :disabled="busy"
              @click="selectDevice(device.id)"
            >
              <span><strong>{{ device.label }}</strong><small>{{ device.detail }}</small></span>
              <em :class="{ offline: !device.online }">{{ device.online ? '在线' : '离线' }}</em>
            </button>
            <p v-if="!devices.length" class="sync-empty">还没有可同步的设备，请先在账号与连接中登录或配对。</p>
          </div>
        </section>

        <section>
          <h3>2. 选择项目</h3>
          <div class="sync-project-list" :aria-busy="loading">
            <p v-if="loading" class="sync-empty">正在读取设备项目…</p>
            <button
              v-for="project in projects"
              v-else
              :key="project.id"
              type="button"
              :class="{ selected: project.id === selectedProjectId }"
              :aria-pressed="project.id === selectedProjectId"
              :disabled="busy"
              @click="selectedProjectId = project.id"
            >
              <Folder :size="17" :stroke-width="1.8" aria-hidden="true" />
              <span><strong>{{ project.name }}</strong><small>{{ project.workRoot }}</small></span>
            </button>
            <p v-if="!loading && selectedDeviceId && !projects.length" class="sync-empty">该设备暂无可用项目。</p>
          </div>
        </section>

        <section>
          <h3>3. 选择模式</h3>
          <div class="sync-mode-list">
            <label :class="{ disabled: busy || selectedDevice?.online === false }">
              <input v-model="mode" type="radio" value="remote" :disabled="busy || selectedDevice?.online === false" />
              <span><strong>远控</strong><small>直接操作该设备上的项目；设备下线后不可用。</small></span>
            </label>
            <label :class="{ disabled: busy }">
              <input v-model="mode" type="radio" value="import" :disabled="busy" />
              <span><strong>导入</strong><small>将项目与会话复制到手机，之后可独立使用。</small></span>
            </label>
          </div>
        </section>

        <p v-if="error" class="sync-error" role="alert">{{ error }}</p>
      </div>

      <footer>
        <button type="button" class="sync-cancel" :disabled="busy" @click="requestClose">取消</button>
        <button
          type="button"
          class="sync-confirm"
          :disabled="busy || !selectedDeviceId || !selectedProjectId || (mode === 'remote' && selectedDevice?.online === false)"
          @click="confirm"
        >{{ busy ? '处理中' : mode === 'remote' ? '开始远控' : '导入到手机' }}</button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Folder } from 'lucide-vue-next'
import type { CoreProject } from '@lamtools/ui'

export interface MobileSyncDevice {
  id: string
  label: string
  detail: string
  online: boolean
}

const props = withDefaults(defineProps<{
  devices: MobileSyncDevice[]
  projects: CoreProject[]
  initialDeviceId?: string
  loading?: boolean
  busy?: boolean
  error?: string
}>(), {
  loading: false,
  busy: false,
  error: '',
  initialDeviceId: '',
})

const emit = defineEmits<{
  close: []
  'load-projects': [deviceId: string]
  confirm: [payload: { deviceId: string; projectId: string; mode: 'remote' | 'import' }]
}>()

const selectedDeviceId = ref('')
const selectedProjectId = ref('')
const mode = ref<'remote' | 'import'>('import')
const selectedDevice = computed(() => props.devices.find((device) => device.id === selectedDeviceId.value))

watch(() => props.projects, (projects) => {
  if (!projects.some((project) => project.id === selectedProjectId.value)) selectedProjectId.value = ''
})

watch([() => props.initialDeviceId, () => props.devices], ([deviceId, devices]) => {
  if (deviceId && deviceId !== selectedDeviceId.value && devices.some((device) => device.id === deviceId)) {
    selectDevice(deviceId)
  }
}, { immediate: true })

watch(() => selectedDevice.value?.online, (online) => {
  if (online === false) mode.value = 'import'
})

function selectDevice(id: string): void {
  selectedDeviceId.value = id
  selectedProjectId.value = ''
  if (selectedDevice.value?.online === false) mode.value = 'import'
  emit('load-projects', id)
}

function confirm(): void {
  if (!selectedDeviceId.value || !selectedProjectId.value || props.busy) return
  emit('confirm', { deviceId: selectedDeviceId.value, projectId: selectedProjectId.value, mode: mode.value })
}

function requestClose(): void {
  if (!props.busy) emit('close')
}
</script>

<style scoped>
.sync-overlay { position: fixed; inset: 0; z-index: var(--z-fullscreen); display: grid; place-items: end center; padding-top: var(--titlebar-offset, 0); background: color-mix(in srgb, #000 38%, transparent); }
.sync-panel { width: min(100%, 620px); max-height: calc(100dvh - var(--titlebar-offset, 0)); display: flex; flex-direction: column; border: 1px solid var(--theme-main-border); border-bottom: 0; border-radius: var(--radius-lg) var(--radius-lg) 0 0; background: var(--theme-main-background); color: var(--theme-main-text); box-shadow: var(--shadow-lg); }
.sync-panel > header, .sync-panel > footer { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-4); }
.sync-panel > header { border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 9%, transparent); }
.sync-panel > header button { width: 40px; height: 40px; border-radius: var(--radius-sm); color: var(--theme-control-text); background: transparent; font-size: 24px; }
.sync-panel > header button:hover, .sync-cancel:hover { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), transparent); }
.sync-panel > header button:active, .sync-cancel:active { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-active), transparent); }
.sync-kicker { color: color-mix(in srgb, var(--theme-main-text) 52%, transparent); font-size: 11px; letter-spacing: .08em; }
h2 { margin-top: 2px; font-size: 20px; }
.sync-body { min-height: 0; display: grid; gap: var(--space-5); padding: var(--space-4); overflow: auto; }
h3 { margin-bottom: var(--space-2); color: color-mix(in srgb, var(--theme-main-text) 72%, transparent); font-size: 12px; font-weight: 650; }
.sync-device-list, .sync-project-list, .sync-mode-list { display: grid; gap: var(--space-2); }
.sync-device, .sync-project-list button, .sync-mode-list label { min-height: 54px; display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3); border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent); border-radius: var(--radius); background: var(--theme-main-soft-background); color: var(--theme-main-text); text-align: left; transition: background var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out); }
.sync-device:hover, .sync-project-list button:hover, .sync-mode-list label:hover { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), var(--theme-main-soft-background)); }
.sync-device:active, .sync-project-list button:active, .sync-mode-list label:active { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), var(--theme-main-soft-background)); }
.sync-device.selected, .sync-project-list button.selected, .sync-mode-list label:has(input:checked) { border-color: color-mix(in srgb, var(--theme-control-text) 55%, transparent); background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), var(--theme-main-soft-background)); }
.sync-device > span, .sync-project-list button > span, .sync-mode-list label > span { min-width: 0; flex: 1; }
strong, small { display: block; }
strong { font-size: 13px; }
small { margin-top: 3px; overflow: hidden; color: color-mix(in srgb, var(--theme-main-text) 58%, transparent); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.sync-device em { color: var(--green); font-size: 11px; font-style: normal; }
.sync-device em.offline { color: color-mix(in srgb, var(--theme-main-text) 45%, transparent); }
.sync-mode-list label.disabled { opacity: .48; }
.sync-empty { padding: var(--space-3); color: color-mix(in srgb, var(--theme-main-text) 52%, transparent); font-size: 12px; line-height: 1.6; }
.sync-error { padding: var(--space-3); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--red) 12%, transparent); color: var(--red); font-size: 12px; }
.sync-panel > footer { padding-bottom: max(var(--space-4), env(safe-area-inset-bottom, 0px)); border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 9%, transparent); justify-content: flex-end; }
.sync-cancel, .sync-confirm { min-height: 40px; padding: 0 var(--space-4); border-radius: var(--radius-sm); }
.sync-cancel { background: transparent; color: var(--theme-control-text); }
.sync-confirm { background: var(--theme-control-background); color: var(--theme-control-text); }
.sync-confirm:hover { filter: brightness(.94); }
.sync-confirm:active { filter: brightness(.9); }
.sync-confirm:disabled { cursor: not-allowed; opacity: .45; }
.sync-panel button:disabled { cursor: not-allowed; opacity: .45; }
@media (prefers-reduced-motion: reduce) {
  .sync-panel { scroll-behavior: auto; }
  .sync-device, .sync-project-list button, .sync-mode-list label { transition: none; }
}
</style>
