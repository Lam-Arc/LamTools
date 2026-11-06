<script setup lang="ts">
/**
 * Pin 环快捷键录制控件：显示可读标签，点「录制」后抓一次真实按键。
 *
 * user:“把桌面端 Pin 环的快捷键设置，从「手动输入字符串」改成「按下物理键录制」”
 * +(不再让用户手写 Ctrl+Alt+Space；按一下物理键就绑定，Esc 退出录制，
 * 只按修饰键不算，清除与恢复默认都给现成按钮。)
 *
 * 组件只负责"拿到 accelerator 字符串"，写配置与注册全局热键仍由设置面板
 * 沿用 runtime.schedulePingSave() 和 bridge.setPingHotkey()。
 */
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { captureHotkey, formatHotkeyLabel } from './hotkeyAccelerator.ts'

const props = withDefaults(
  defineProps<{
    /** 当前生效的 accelerator（来自 runtime.config.ping.hotkey）。 */
    accelerator: string
    /** 「恢复默认」写回的值。 */
    fallback?: string
  }>(),
  { fallback: 'Ctrl+Alt+Space' },
)

const emit = defineEmits<{ commit: [accelerator: string] }>()

const trigger = ref<HTMLButtonElement | null>(null)
const recording = ref(false)
const status = ref('')
const failed = ref(false)

const label = computed(() => formatHotkeyLabel(props.accelerator))

function stopRecording(nextStatus = '', isFailure = false): void {
  recording.value = false
  status.value = nextStatus
  failed.value = isFailure
  window.removeEventListener('keydown', onKeydown, true)
}

function onKeydown(event: KeyboardEvent): void {
  if (!recording.value) return
  const result = captureHotkey({
    key: event.key,
    ctrlKey: event.ctrlKey,
    shiftKey: event.shiftKey,
    altKey: event.altKey,
    metaKey: event.metaKey,
    repeat: event.repeat,
  })

  // 录制态下吃掉所有按键：Escape 只用来取消录制，不能顺手关掉设置页；
  // 其他组合也不能在这期间触发页面上的全局快捷键（Ctrl+K 搜索、清主题重载等）。
  // 焦点由 <button> 承载，不用 input，避免被输入框的按键豁免与输入法截走。
  event.preventDefault()
  event.stopPropagation()

  if (result.status === 'pending') {
    status.value = result.hint
    failed.value = false
    return
  }
  if (result.status === 'cancelled') {
    stopRecording('已取消录制')
    return
  }
  if (result.status === 'rejected') {
    // 组合不成立时留在录制态，用户可以直接换一组键再按。
    status.value = result.reason
    failed.value = true
    return
  }

  stopRecording(`已绑定 ${result.label}`)
  emit('commit', result.accelerator)
  void nextTick(() => trigger.value?.focus())
}

function startRecording(): void {
  status.value = '请按下组合键（需含 Ctrl / Alt / Shift / Win，Esc 取消）'
  failed.value = false
  recording.value = true
  window.addEventListener('keydown', onKeydown, true)
  // 键盘用户点按钮后焦点留在按钮上，录制结束能接着操作。
  void nextTick(() => trigger.value?.focus())
}

function toggleRecording(): void {
  if (recording.value) stopRecording('已取消录制')
  else startRecording()
}

function clearHotkey(): void {
  stopRecording('已清除，快捷键已解绑')
  emit('commit', '')
}

function restoreDefault(): void {
  stopRecording(`已恢复默认 ${formatHotkeyLabel(props.fallback)}`)
  emit('commit', props.fallback)
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown, true)
})
</script>

<template>
  <div class="hotkey" :class="{ 'hotkey--recording': recording }">
    <span class="hotkey__value" :class="{ 'hotkey__value--empty': !accelerator }">{{ label }}</span>
    <button
      ref="trigger"
      type="button"
      tabindex="0"
      class="hotkey__record"
      :aria-pressed="recording"
      :aria-label="recording ? '正在录制快捷键，按下组合键或按 Esc 取消' : `录制快捷键，当前为 ${label}`"
      @click="toggleRecording"
    >
      {{ recording ? '录制中…' : '录制' }}
    </button>
    <button type="button" :disabled="!accelerator" @click="clearHotkey">清除</button>
    <button type="button" @click="restoreDefault">恢复默认</button>
    <span class="hotkey__status" :class="{ 'hotkey__status--error': failed }" role="status" aria-live="polite">
      {{ status }}
    </span>
  </div>
</template>

<style scoped>
.hotkey {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  justify-content: flex-end;
}

.hotkey__value {
  min-width: 92px;
  padding: 3px 8px;
  border-radius: 7px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(0, 0, 0, 0.3);
  font-size: 11px;
  text-align: center;
  letter-spacing: 0.02em;
}

.hotkey__value--empty {
  color: rgba(196, 210, 232, 0.55);
}

.hotkey--recording .hotkey__value {
  border-color: rgba(160, 200, 255, 0.72);
  box-shadow: 0 0 0 2px rgba(120, 170, 255, 0.18);
}

.hotkey button {
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.06);
  color: inherit;
  font-size: 11px;
  cursor: pointer;
}

.hotkey button:disabled {
  opacity: 0.45;
  cursor: default;
}

.hotkey__record[aria-pressed='true'] {
  border-color: rgba(160, 200, 255, 0.8);
  background: rgba(120, 170, 255, 0.22);
}

.hotkey__status {
  flex-basis: 100%;
  text-align: right;
  font-size: 10px;
  color: rgba(196, 210, 232, 0.66);
  line-height: 1.5;
}

.hotkey__status--error {
  color: #ffb4b4;
}
</style>
