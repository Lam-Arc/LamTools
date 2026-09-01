<template>
  <section class="theme-area-card">
    <h4>{{ label }}</h4>
    <div class="gradient-stop-list">
      <div
        v-for="(stop, index) in stops"
        :key="index"
        class="gradient-stop-row"
      >
        <span>{{ index + 1 }}</span>
        <input
          v-model="stop.color"
          type="color"
          @change="$emit('sort-stops')"
        />
        <input
          v-model="stop.color"
          @change="$emit('sort-stops')"
        />
        <input
          v-model.number="stop.position"
          type="number"
          min="0"
          max="100"
          step="1"
          @change="$emit('sort-stops')"
        />
        <button
          type="button"
          :disabled="stops.length <= 1"
          @click="$emit('remove-stop', index)"
        >删</button>
      </div>
      <button
        class="small-btn"
        type="button"
        :disabled="stops.length >= 8"
        @click="$emit('add-stop')"
      >+ 添加节点</button>
    </div>
    <label class="field width-field">
      <span>渐变角度 <em>{{ angle }}deg</em></span>
      <div class="width-control">
        <input
          v-model.number="angleModel"
          type="range"
          min="0"
          max="360"
          step="5"
        />
        <input
          v-model.number="angleModel"
          type="number"
          min="0"
          max="360"
          step="5"
        />
      </div>
    </label>
    <label v-if="showOpacity" class="field width-field">
      <span>透明度 <em>{{ opacityPct }}</em></span>
      <div class="width-control">
        <input
          v-model.number="opacityModel"
          type="range"
          min="0.1"
          max="1"
          step="0.05"
        />
        <input
          v-model.number="opacityModel"
          type="number"
          min="0.1"
          max="1"
          step="0.05"
        />
      </div>
    </label>
    <label class="field color-field">文本颜色
      <span>
        <input
          v-model="textColorModel"
          type="color"
          @change="$emit('update:text-color', textColorModel)"
        />
        <input
          v-model="textColorModel"
          @change="$emit('update:text-color', textColorModel)"
        />
      </span>
    </label>
  </section>
</template>

<script setup lang="ts">
/**
 * ThemeAreaEditor — single theme area (backdrop/main/composer/control) editor
 *
 * Handles: gradient stops, angle, opacity, text color.
 */
import { computed } from 'vue'
import type { ThemeStop } from '../helpers/theme'

const props = defineProps<{
  label: string
  stops: ThemeStop[]
  angle: number
  opacity: number
  textColor: string
  showOpacity?: boolean
}>()

const emit = defineEmits<{
  'update:stops': [stops: ThemeStop[]]
  'update:angle': [angle: number]
  'update:opacity': [opacity: number]
  'update:text-color': [color: string]
  'add-stop': []
  'remove-stop': [index: number]
  'sort-stops': []
}>()

const angleModel = computed({
  get: () => props.angle,
  set: (val) => emit('update:angle', val),
})

const opacityModel = computed({
  get: () => props.opacity,
  set: (val) => emit('update:opacity', val),
})

const textColorModel = computed({
  get: () => props.textColor,
  set: (val) => emit('update:text-color', val),
})

const opacityPct = computed(() => `${Math.round(props.opacity * 100)}%`)
</script>
