<template>
  <span>{{ displayed }}</span>
</template>

<script setup lang="ts">
/**
 * TypewriterText — displays text character-by-character on mount.
 *
 * Duration is clamped to 200–500 ms. Short messages feel snappy;
 * long messages still finish within the upper bound.
 */
import { ref, onMounted, onUnmounted } from 'vue'

const props = withDefaults(defineProps<{
  text: string
  duration?: number
}>(), {
  duration: 400,
})

const displayed = ref('')
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  const chars = props.text.split('')
  if (chars.length === 0) return

  // Clamp total duration to [200, 500] ms
  const clampedDuration = Math.min(500, Math.max(200, props.duration))
  const intervalMs = Math.max(16, clampedDuration / chars.length)
  let i = 0

  timer = setInterval(() => {
    if (i < chars.length) {
      displayed.value = props.text.slice(0, i + 1)
      i++
    } else {
      if (timer) {
        clearInterval(timer)
        timer = null
      }
    }
  }, intervalMs)
})

onUnmounted(() => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
})
</script>
