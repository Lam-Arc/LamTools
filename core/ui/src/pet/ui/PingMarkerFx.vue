<script setup lang="ts">
/**
 * Ping 标记的轻量动画：约 2–3 秒的脉冲确认。
 *
 * user:“? 标记在指向处显示约 2–3 秒的轻微动画”+
 * (动画只是给用户的视觉回执，不参与请求时序：截图与提交在动画开始前就已经发出，
 *  所以标记再漂亮也不会阻塞 Agent。)
 * user:"ping 环跟桌宠应当是解耦的，它们是两个独立的功能"+
 * (组件只依赖 Ping 运行时（ping/），不引用桌宠运行时与宠物实例。)
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { PingRuntime } from '../ping/usePingRuntime.ts'

const props = defineProps<{ ping: PingRuntime }>()
const elapsed = ref(0)
let frame = 0
let startedAt = 0

const scale = computed(() => Math.max(0.1, props.ping.overlay.width / Math.max(1, window.innerWidth)))

const position = computed(() => ({
  left: `${(props.ping.markerFx.x - props.ping.overlay.x) / scale.value}px`,
  top: `${(props.ping.markerFx.y - props.ping.overlay.y) / scale.value}px`,
}))

const progress = computed(() => {
  const duration = Math.max(600, props.ping.config.ping.markerMs)
  return Math.min(1, elapsed.value / duration)
})

const glyph = computed(() => {
  const kind = props.ping.markerFx.kind
  if (kind === 'question') return '?'
  if (kind === 'exclamation') return '!'
  if (kind === 'select') return '框'
  return '记'
})

watch(() => props.ping.markerFx.startedAt, () => {
  startedAt = performance.now()
  cancelAnimationFrame(frame)
  const tick = () => {
    elapsed.value = performance.now() - startedAt
    if (props.ping.markerFx.visible) {
      frame = requestAnimationFrame(tick)
    }
  }
  frame = requestAnimationFrame(tick)
})

onBeforeUnmount(() => cancelAnimationFrame(frame))
</script>

<template>
  <div
    v-if="ping.markerFx.visible"
    class="marker-fx"
    :style="position"
    aria-hidden="true"
  >
    <span
      class="marker-fx__ring"
      :style="{
        borderColor: ping.markerFx.color,
        opacity: String(1 - progress),
        transform: `translate(-50%, -50%) scale(${1 + progress * 1.6})`,
      }"
    />
    <span class="marker-fx__core" :style="{ borderColor: ping.markerFx.color, color: ping.markerFx.color }">
      {{ glyph }}
    </span>
    <span class="marker-fx__label" :style="{ opacity: String(1 - progress) }">
      {{ ping.markerFx.label }}
    </span>
  </div>
</template>

<style scoped>
.marker-fx {
  position: absolute;
  z-index: 30;
  pointer-events: none;
  transform: translate(-50%, -50%);
}

.marker-fx__ring {
  position: absolute;
  left: 0;
  top: 0;
  width: 54px;
  height: 54px;
  border-radius: 50%;
  border: 2px solid;
  display: block;
  transition: opacity 80ms linear;
}

.marker-fx__core {
  position: absolute;
  left: 0;
  top: 0;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 2px solid;
  background: rgba(14, 17, 22, 0.55);
  font-size: 15px;
  font-weight: 700;
  transform: translate(-50%, -50%);
  backdrop-filter: blur(6px);
}

.marker-fx__label {
  position: absolute;
  left: 22px;
  top: -34px;
  white-space: nowrap;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(14, 17, 22, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.16);
  font-size: 11px;
  color: #e9f0fb;
}
</style>
