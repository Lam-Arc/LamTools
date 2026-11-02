<script setup lang="ts">
/** 角色右键菜单：设置、绑定、临时会话、动作、显示/隐藏、移除。 */
import { computed, nextTick, ref, watch, type PropType } from 'vue'
import type { PetRuntime } from './usePetRuntime.ts'

const props = defineProps<{
  runtime: PetRuntime
  open: boolean
  x: number
  y: number
  petId: string
}>()

const emit = defineEmits<{ close: []; settings: [] }>()

const pet = computed(() => props.runtime.world.value?.get(props.petId) || null)
const binding = computed(() => props.runtime.agents.value?.bindings.pets[props.petId] || null)

// user:"剩下的项全都超出屏幕了，响应式设计，自动避让一下屏幕边缘"+
// (桌宠常在屏幕底部，菜单照光标位置向下展开会整体出屏。打开后按实测尺寸
// 把菜单收回视口内：先右超出往左收，再下超出往上收。)
const menuEl = ref<HTMLElement | null>(null)
const adjusted = ref({ x: props.x, y: props.y })

watch(
  () => [props.open, props.x, props.y] as const,
  async ([open]) => {
    if (!open) return
    adjusted.value = { x: props.x, y: props.y }
    await nextTick()
    const el = menuEl.value
    if (!el) return
    const box = el.getBoundingClientRect()
    const margin = 8
    let x = props.x
    let y = props.y
    if (x + box.width + margin > window.innerWidth) {
      x = Math.max(margin, window.innerWidth - box.width - margin)
    }
    if (y + box.height + margin > window.innerHeight) {
      y = Math.max(margin, window.innerHeight - box.height - margin)
    }
    adjusted.value = { x, y }
  },
  { immediate: true },
)

function act(fn: () => void): void {
  fn()
  emit('close')
}

function toggleDebug(key: 'terrain' | 'colliders' | 'path' | 'velocity'): void {
  props.runtime.debug[key] = !props.runtime.debug[key]
  props.runtime.scheduleSave()
}
</script>

<template>
  <div v-if="open" ref="menuEl" class="pet-menu" data-pet-hit :style="{ left: `${adjusted.x}px`, top: `${adjusted.y}px` }" @pointerdown.stop>
    <div class="pet-menu__head">{{ pet?.name || petId }}</div>
    <button type="button" @click="act(() => runtime.openSessionPicker('pet', petId))">
      绑定会话…（当前：{{ binding?.sessionId ? binding.sessionId.slice(0, 8) : '未绑定' }}{{ binding?.temporarySessionId ? ' · 临时' : '' }}）
    </button>
    <button
      v-if="binding?.temporarySessionId"
      type="button"
      @click="act(() => runtime.agents.value?.clearPetTemporary(petId))"
    >恢复持久默认绑定</button>
    <hr>
    <button type="button" @click="act(() => runtime.playAction(petId, 'dance'))">跳舞</button>
    <button type="button" @click="act(() => runtime.playAction(petId, 'jump_happy'))">开心跳</button>
    <button type="button" @click="act(() => runtime.togglePetVisible(petId))">
      {{ pet?.visible ? '隐藏这只' : '显示这只' }}
    </button>
    <hr>
    <button type="button" @click="act(() => toggleDebug('terrain'))">
      {{ runtime.debug.terrain ? '✓ ' : '' }}显示地形线
    </button>
    <button type="button" @click="act(() => toggleDebug('colliders'))">
      {{ runtime.debug.colliders ? '✓ ' : '' }}显示碰撞体与 Hitbox
    </button>
    <button type="button" @click="act(() => toggleDebug('path'))">
      {{ runtime.debug.path ? '✓ ' : '' }}显示寻路路径（并可点击地图设目标）
    </button>
    <button type="button" @click="act(() => toggleDebug('velocity'))">
      {{ runtime.debug.velocity ? '✓ ' : '' }}显示速度向量
    </button>
    <hr>
    <button type="button" @click="act(() => emit('settings'))">桌宠设置…</button>
    <button type="button" class="pet-menu__danger" @click="act(() => runtime.removePet(petId))">移除这只桌宠</button>
    <button type="button" @click="act(() => void runtime.shutdown())">关闭桌宠覆盖层</button>
  </div>
</template>

<style scoped>
.pet-menu {
  position: absolute;
  z-index: 40;
  min-width: 240px;
  padding: 6px;
  border-radius: 12px;
  background: rgba(18, 20, 25, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.42);
  backdrop-filter: blur(14px);
  font-size: 12px;
  color: #e8eef8;
  pointer-events: auto;
}

.pet-menu__head {
  padding: 4px 8px 6px;
  font-size: 11px;
  color: rgba(200, 214, 235, 0.66);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 4px;
}

.pet-menu button {
  display: block;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
  font-size: 12px;
  cursor: pointer;
}

.pet-menu button:hover {
  background: rgba(255, 255, 255, 0.1);
}

.pet-menu__danger {
  color: #ff9d9d;
}

.pet-menu hr {
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  margin: 4px 2px;
}
</style>
