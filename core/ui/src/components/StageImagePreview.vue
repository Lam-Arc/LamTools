<template>
  <div class="stage-image" @wheel.prevent="onWheel" @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="onPointerUp" @pointerleave="onPointerUp">
    <div class="stage-image-viewport" :style="transformStyle">
      <img :src="src" :alt="label || ''" draggable="false" @load="onLoad" @error="onError" />
    </div>
    <div v-if="error" class="stage-image-error">
      <span>无法加载图片</span>
    </div>
    <div class="stage-image-controls">
      <button type="button" @click="zoom = 1; panX = 0; panY = 0" title="重置">1:1</button>
      <span>{{ Math.round(zoom * 100) }}%</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  src: string
  label?: string
}>()

const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
const error = ref(false)
const dragging = ref(false)
const lastX = ref(0)
const lastY = ref(0)

const transformStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoom.value})`,
}))

function onLoad() {
  error.value = false
}
function onError() {
  error.value = true
}
function onWheel(e: WheelEvent) {
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  zoom.value = Math.min(10, Math.max(0.1, zoom.value * delta))
}
function onPointerDown(e: PointerEvent) {
  dragging.value = true
  lastX.value = e.clientX
  lastY.value = e.clientY
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}
function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  panX.value += e.clientX - lastX.value
  panY.value += e.clientY - lastY.value
  lastX.value = e.clientX
  lastY.value = e.clientY
}
function onPointerUp() {
  dragging.value = false
}
</script>

<style scoped>
.stage-image {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  background: transparent;
}
.stage-image:active { cursor: grabbing; }
.stage-image-viewport {
  transition: transform 0.05s linear;
  max-width: 100%;
  max-height: 100%;
}
.stage-image-viewport img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  user-select: none;
  -webkit-user-drag: none;
}
.stage-image-error {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #888;
  font-size: 14px;
}
.stage-image-controls {
  position: absolute;
  bottom: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border-radius: 8px;
  background: rgba(0,0,0,0.6);
  color: #ccc;
  font-size: 12px;
}
.stage-image-controls button {
  border: 0;
  background: rgba(255,255,255,0.1);
  color: #ccc;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 12px;
}
.stage-image-controls button:hover { background: rgba(255,255,255,0.2); }
</style>
