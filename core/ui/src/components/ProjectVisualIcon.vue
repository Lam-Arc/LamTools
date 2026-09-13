<template>
  <span
    class="project-visual-icon"
    :class="{ 'project-visual-icon--gradient': isGradient, 'project-visual-icon--swatch': swatch }"
    :style="visualStyle"
    aria-hidden="true"
  >
    <component v-if="!swatch" :is="iconComponent" :size="iconSize" :stroke-width="1.8" />
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  BookOpen,
  BriefcaseBusiness,
  Code2,
  Folder,
  Lightbulb,
  Palette,
  Rocket,
  Sparkles,
} from 'lucide-vue-next'
import {
  CORE_PROJECT_COLOR_KEYS,
  CORE_PROJECT_GRADIENT_COLOR_KEYS,
  CORE_PROJECT_ICON_KEYS,
  DEFAULT_CORE_PROJECT_COLOR_KEY,
  DEFAULT_CORE_PROJECT_ICON_KEY,
  type CoreProjectColorKey,
  type CoreProjectIconKey,
} from '../projects/types'

const props = withDefaults(defineProps<{
  iconKey?: string
  colorKey?: string
  size?: number
  iconSize?: number
  swatch?: boolean
}>(), {
  iconKey: DEFAULT_CORE_PROJECT_ICON_KEY,
  colorKey: DEFAULT_CORE_PROJECT_COLOR_KEY,
  size: 24,
  iconSize: 15,
  swatch: false,
})

const iconComponents = {
  folder: Folder,
  code: Code2,
  idea: Lightbulb,
  design: Palette,
  docs: BookOpen,
  work: BriefcaseBusiness,
  rocket: Rocket,
  sparkles: Sparkles,
} as const

const colorValues: Record<CoreProjectColorKey, string> = {
  gray: '#9ba0ad',
  blue: '#3978f6',
  violet: '#7359ee',
  pink: '#cf50ae',
  red: '#df5361',
  orange: '#ee8738',
  green: '#329e69',
  cyan: '#1d9eb3',
  sunrise: 'linear-gradient(135deg, #ff5f68 0%, #ffc33d 100%)',
  aurora: 'linear-gradient(135deg, #31b97c 0%, #2fc7d4 100%)',
  ocean: 'linear-gradient(135deg, #19b8ef 0%, #3269f5 100%)',
  'violet-sky': 'linear-gradient(135deg, #366cf6 0%, #9256ed 100%)',
  berry: 'linear-gradient(135deg, #e34c9d 0%, #774ee8 100%)',
  ember: 'linear-gradient(135deg, #e94858 0%, #f19a35 100%)',
  forest: 'linear-gradient(135deg, #3b9b5f 0%, #187e83 100%)',
  prism: 'linear-gradient(135deg, #ff8b3d 0%, #e952a9 46%, #5368f7 100%)',
}

const normalizedIconKey = computed<CoreProjectIconKey>(() => (
  CORE_PROJECT_ICON_KEYS.includes(props.iconKey as CoreProjectIconKey)
    ? props.iconKey as CoreProjectIconKey
    : DEFAULT_CORE_PROJECT_ICON_KEY
))
const normalizedColorKey = computed<CoreProjectColorKey>(() => (
  CORE_PROJECT_COLOR_KEYS.includes(props.colorKey as CoreProjectColorKey)
    ? props.colorKey as CoreProjectColorKey
    : DEFAULT_CORE_PROJECT_COLOR_KEY
))
const isGradient = computed(() => CORE_PROJECT_GRADIENT_COLOR_KEYS.includes(
  normalizedColorKey.value as typeof CORE_PROJECT_GRADIENT_COLOR_KEYS[number],
))
const iconComponent = computed(() => iconComponents[normalizedIconKey.value])
const visualStyle = computed(() => ({
  '--project-visual-size': `${props.size}px`,
  '--project-visual-color': colorValues[normalizedColorKey.value],
}))
</script>

<style scoped>
.project-visual-icon {
  width: var(--project-visual-size);
  height: var(--project-visual-size);
  display: inline-grid;
  place-items: center;
  box-sizing: border-box;
  flex: 0 0 auto;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--project-visual-color);
}

.project-visual-icon--gradient {
  background: var(--project-visual-color);
  color: #ffffff;
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 14%);
}

.project-visual-icon--swatch {
  border-radius: 50%;
  background: var(--project-visual-color);
}
</style>
