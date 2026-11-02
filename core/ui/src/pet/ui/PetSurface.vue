<script setup lang="ts">
/**
 * 桌宠覆盖层根组件。
 *
 * 这一层是全屏透明的：只有角色、气泡、卡片、轮盘所在矩形会接收鼠标，其余位置
 * 由 Rust 侧的命中测试切回穿透，所以底下的 PDF/浏览器照常可用。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import PetStage from './PetStage.vue'
import PetBubbles from './PetBubbles.vue'
import PetPreview from './PetPreview.vue'
import PetSettingsPanel from './PetSettingsPanel.vue'
import PetContextMenu from './PetContextMenu.vue'
import SessionPicker from './SessionPicker.vue'
import { usePetRuntime } from './usePetRuntime.ts'
import { useOverlayTheme } from './overlayTheme.ts'

// user:“把样式也对齐，这是第一步”+(覆盖层跟随主界面主题：同一份偏好、同一套令牌。)
useOverlayTheme()

const runtime = usePetRuntime()
const stage = ref<InstanceType<typeof PetStage> | null>(null)
const menu = ref<{ open: boolean; x: number; y: number; petId: string }>({ open: false, x: 0, y: 0, petId: '' })
const settingsOpen = computed({
  get: () => runtime.ui.settingsOpen,
  set: (value: boolean) => { runtime.ui.settingsOpen = value },
})
const dragState = ref<{ petId: string; startX: number; startY: number; dragging: boolean; startedAt: number } | null>(null)
const lastClick = ref<{ at: number; petId: string }>({ at: 0, petId: '' })

onMounted(() => {
  void runtime.boot()
  window.addEventListener('keydown', onKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
  void runtime.shutdown()
})

function onKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    // Ping 的 Esc 取消在 Ping 自己的窗口里处理。
    if (menu.value.open) menu.value.open = false
  }
}

function onPointerDown(event: PointerEvent): void {
  const point = { x: event.clientX * scaleX() + runtime.overlay.x, y: event.clientY * scaleY() + runtime.overlay.y }
  const hit = runtime.hitPet(point.x, point.y)
  if (!hit) {
    menu.value.open = false
    if (runtime.debug.path) runtime.setPetDestination(runtime.petRecords.value[0]?.id || '', point)
    return
  }
  dragState.value = { petId: hit.pet.id, startX: point.x, startY: point.y, dragging: false, startedAt: performance.now() }
  ;(event.target as HTMLElement).setPointerCapture?.(event.pointerId)
}

function onPointerMove(event: PointerEvent): void {
  const point = { x: event.clientX * scaleX() + runtime.overlay.x, y: event.clientY * scaleY() + runtime.overlay.y }
  const state = dragState.value
  if (!state) return
  const moved = Math.hypot(point.x - state.startX, point.y - state.startY)
  // 点击与拖拽靠移动阈值区分：快速单击不会被当成拖拽。
  if (!state.dragging && moved > 6) {
    state.dragging = true
    runtime.petDragStart(state.petId, point)
  }
  if (state.dragging) runtime.petDragMove(state.petId, point)
}

function onPointerUp(event: PointerEvent): void {
  const state = dragState.value
  dragState.value = null
  if (!state) return
  if (state.dragging) {
    runtime.petDragEnd(state.petId)
    return
  }
  const point = { x: event.clientX * scaleX() + runtime.overlay.x, y: event.clientY * scaleY() + runtime.overlay.y }
  const hit = runtime.hitPet(point.x, point.y)
  if (!hit) return
  const now = performance.now()
  const isDouble = lastClick.value.petId === state.petId && now - lastClick.value.at < 320
  lastClick.value = { at: now, petId: state.petId }
  runtime.clickPet(state.petId, hit.localX, hit.localY, isDouble)
}

function onContextMenu(event: MouseEvent): void {
  const point = { x: event.clientX * scaleX() + runtime.overlay.x, y: event.clientY * scaleY() + runtime.overlay.y }
  const hit = runtime.hitPet(point.x, point.y)
  event.preventDefault()
  if (!hit) {
    menu.value = { open: false, x: 0, y: 0, petId: '' }
    return
  }
  menu.value = { open: true, x: event.clientX, y: event.clientY, petId: hit.pet.id }
}

function scaleX(): number {
  return runtime.overlay.width / Math.max(1, window.innerWidth)
}

function scaleY(): number {
  return runtime.overlay.height / Math.max(1, window.innerHeight)
}

function openSettings(): void {
  menu.value.open = false
  settingsOpen.value = true
}
</script>

<template>
  <div
    class="pet-surface"
    data-region="pet-surface"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @contextmenu="onContextMenu"
  >
    <PetStage ref="stage" :runtime="runtime" />

    <PetBubbles :runtime="runtime" />
    <!-- user:“你看看 ping 环 要不也自己做窗口？”+
         (轮盘/标记/标注/会话选择器/卡片全部搬到独立的 Ping 覆盖层窗口；
          桌宠覆盖层只负责角色、气泡、右键菜单与设置。) -->
    <SessionPicker
      :picker="runtime.sessionPicker"
      :load-sessions="runtime.loadSessions"
      :choose-session="runtime.chooseSession"
      :close="() => { runtime.sessionPicker.open = false }"
    />

    <PetContextMenu
      :runtime="runtime"
      :open="menu.open"
      :x="menu.x"
      :y="menu.y"
      :pet-id="menu.petId"
      @close="menu.open = false"
      @settings="openSettings"
    />

    <PetPreview v-if="runtime.importer.open" :runtime="runtime" />
    <PetSettingsPanel v-if="settingsOpen" :runtime="runtime" @close="settingsOpen = false" />

    <div v-if="!runtime.ready.value" class="pet-boot" role="status">
      <div class="pet-boot__text">
        {{ runtime.booting.value ? '桌宠正在启动…' : '桌宠未启动' }}
      </div>
      <div v-if="runtime.errors.value.length" class="pet-boot__errors">
        <div v-for="error in runtime.errors.value.slice(-3)" :key="error.at" class="pet-boot__error">
          [{{ error.scope }}] {{ error.message }}
        </div>
        <button type="button" class="pet-boot__retry" @click="runtime.boot()">重试</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pet-surface {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: transparent;
  /* 覆盖层本身不吃指针事件：命中区由 Rust 侧按矩形切换，这里只保证不会挡住画布元素。 */
  color: #f2f5fa;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.pet-boot {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  padding: 18px 22px;
  border-radius: 16px;
  background: rgba(24, 27, 33, 0.82);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.38);
  font-size: 13px;
  max-width: 460px;
}

.pet-boot__errors {
  margin-top: 10px;
  display: grid;
  gap: 6px;
}

.pet-boot__error {
  color: #ffb4b4;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  line-height: 1.5;
  word-break: break-all;
}

.pet-boot__retry {
  justify-self: start;
  margin-top: 4px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.08);
  color: inherit;
  font-size: 12px;
  cursor: pointer;
}
</style>
