<template>
  <section ref="themeRootEl" class="theme-editor-root">
    <section ref="dialogEl" class="theme-editor-dialog theme-editor-dialog--inline" aria-labelledby="theme-editor-title">
          <header class="theme-editor-head">
            <div>
              <h2 id="theme-editor-title">主题</h2>
            </div>
            <button class="small-btn quiet" type="button" @click="$emit('reset-theme')">恢复默认</button>
          </header>

          <div class="theme-editor-scroll">
            <section class="theme-editor-section">
              <div class="theme-section-copy">
                <strong>外观</strong>
                <span>选择主题随系统变化，或固定在一个模式。</span>
              </div>
              <div class="theme-mode-options" role="radiogroup" aria-label="外观模式">
                <button
                  v-for="mode in appearanceModes"
                  :key="mode.value"
                  class="theme-mode-option"
                  :class="{ 'is-active': themeMode === mode.value }"
                  type="button"
                  role="radio"
                  :aria-checked="themeMode === mode.value ? 'true' : 'false'"
                  :data-theme-mode="mode.value"
                  @click="setThemeMode(mode.value)"
                >
                  <span aria-hidden="true" />
                  {{ mode.label }}
                </button>
              </div>
            </section>

            <section class="theme-editor-section">
              <div class="theme-section-copy">
                <strong>预设颜色</strong>
                <span>当前显示{{ effectiveThemeMode === 'dark' ? '深色' : '浅色' }}版本；切换后立即生效。</span>
              </div>
              <div class="theme-preset-list" role="list">
                <button
                  v-for="preset in presets"
                  :key="preset.id"
                  class="theme-preset"
                  :class="{ 'is-active': isPresetActive(preset) }"
                  type="button"
                  role="listitem"
                  :data-theme-preset="preset.id"
                  @click="selectPreset(preset, $event.currentTarget as HTMLElement)"
                >
                  <span class="theme-preset-swatch" :style="presetBackdropStyle(preset)">
                    <i :style="presetMainStyle(preset)" />
                    <b :style="presetControlStyle(preset)" />
                  </span>
                  <span>{{ preset.name }}</span>
                  <em v-if="isPresetActive(preset)" aria-label="当前主题">✓</em>
                </button>
              </div>
            </section>

            <section class="theme-editor-section theme-editor-preview-section">
              <div class="theme-section-copy">
                <strong>实时预览</strong>
                <span>主题会即时同步到当前 Core 界面。</span>
              </div>
              <ThemePreview
                ref="previewEl"
                :backdrop-style="themePreviewStyle"
                :main-style="themePreviewMainStyle"
                :composer-style="themePreviewComposerStyle"
                :control-style="themePreviewControlStyle"
                :product-name="productName"
                :content-description="contentDescription"
                :area-stops="previewAreaStops"
                interactive
                @select-area="openAreaPopover"
              />
            </section>

            <details class="theme-advanced">
              <summary>
                <span>
                  <strong>高级调整</strong>
                  <small>颜色节点、透明度与界面密度</small>
                </span>
              </summary>
              <div class="theme-advanced-content">
                <section class="theme-density-section">
                  <div class="theme-section-copy">
                    <strong>界面密度</strong>
                    <span>调整内容区的信息密度。</span>
                  </div>
                  <div class="density-options" role="group" aria-label="界面密度">
                    <button
                      v-for="option in densityOptions"
                      :key="option.value"
                      type="button"
                      :data-density="option.value"
                      :class="{ active: density === option.value }"
                      @click="$emit('update:density', option.value)"
                    >{{ option.label }}</button>
                  </div>
                  <label v-if="contentWidth" class="field theme-width-field">内容宽度
                    <input
                      :value="contentWidth"
                      type="range"
                      min="560"
                      max="1120"
                      step="20"
                      @input="$emit('update:content-width', Number(($event.target as HTMLInputElement).value))"
                    />
                  </label>
                </section>
                <div class="theme-area-list">
                  <section v-for="area in areas" :key="area.key" class="theme-area-row">
                    <button
                      class="theme-area-summary"
                      :class="{ 'is-expanded': activeArea === area.key }"
                      type="button"
                      :aria-expanded="activeArea === area.key ? 'true' : 'false'"
                      :data-theme-area="area.key"
                      @click="openAreaPopover(area.key)"
                    >
                      <span class="theme-area-summary-name">{{ area.label }}</span>
                      <span class="theme-area-nodes" :aria-label="`${area.label}颜色节点`">
                        <span v-for="(stop, index) in getStops(area.key)" :key="`${stop.color}-${index}`" class="theme-area-node">
                          <i :style="{ background: stop.color }" />
                        </span>
                      </span>
                    </button>
                  </section>
                </div>
              </div>
            </details>
          </div>

    </section>
    <Teleport to="body">
      <Transition @enter="animateAreaPopoverEnter" @leave="animateAreaPopoverLeave">
        <div v-if="activeArea && activeAreaConfig" class="theme-area-popover-overlay" @click.self="closeAreaPopover">
          <section ref="areaPopoverEl" class="theme-area-popover" role="dialog" aria-modal="true" :aria-labelledby="`theme-area-popover-${activeArea}`">
            <header class="theme-area-popover-head">
              <div>
                <span>详细调整</span>
                <h3 :id="`theme-area-popover-${activeArea}`">{{ activeAreaConfig.label }}</h3>
              </div>
              <button class="theme-area-popover-close" type="button" data-theme-area-popover-close aria-label="关闭详细调整" @click="closeAreaPopover">×</button>
            </header>
            <ThemeAreaEditor
              :label="activeAreaConfig.label"
              :stops="getStops(activeArea)"
              :angle="getAngle(activeArea)"
              :opacity="getOpacity(activeArea)"
              :text-color="getTextColor(activeArea)"
              :show-opacity="activeAreaConfig.showOpacity"
              @update:stops="(stops) => $emit('update:stops', activeArea!, stops)"
              @update:angle="(angle) => $emit('update:angle', activeArea!, angle)"
              @update:opacity="(opacity) => $emit('update:opacity', activeArea!, opacity)"
              @update:text-color="(color) => $emit('update:text-color', activeArea!, color)"
              @add-stop="$emit('add-stop', activeArea!)"
              @remove-stop="(index) => $emit('remove-stop', activeArea!, index)"
              @sort-stops="$emit('sort-stops', activeArea!)"
            />
          </section>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { gsap } from 'gsap'
import ThemeAreaEditor from './ThemeAreaEditor.vue'
import ThemePreview from './ThemePreview.vue'
import { gradientFromStops, themeForMode, type ThemeArea, type ThemeMode, type ThemePreset, type ThemeStop } from '../helpers/theme'

const props = withDefaults(defineProps<{
  productName?: string
  contentDescription?: string
  density: string
  densityOptions: Array<{ value: string; label: string }>
  contentWidth?: number
  themeMode?: ThemeMode
  effectiveThemeMode?: 'light' | 'dark'
  getStops: (area: ThemeArea) => ThemeStop[]
  getAngle: (area: ThemeArea) => number
  getOpacity: (area: ThemeArea) => number
  getTextColor: (area: ThemeArea) => string
  presets: ThemePreset[]
  themePreviewStyle: Record<string, string>
  themePreviewMainStyle: Record<string, string>
  themePreviewComposerStyle: Record<string, string>
  themePreviewControlStyle: Record<string, string>
}>(), {
  productName: 'LamTools Core',
  contentDescription: 'Core 工作区',
  themeMode: 'system',
  effectiveThemeMode: 'dark',
})

const emit = defineEmits<{
  'reset-theme': []
  'apply-preset': [preset: ThemePreset]
  'update:theme-mode': [mode: ThemeMode]
  'update:density': [value: string]
  'update:content-width': [value: number]
  'update:stops': [area: ThemeArea, stops: ThemeStop[]]
  'update:angle': [area: ThemeArea, angle: number]
  'update:opacity': [area: ThemeArea, value: number]
  'update:text-color': [area: ThemeArea, color: string]
  'add-stop': [area: ThemeArea]
  'remove-stop': [area: ThemeArea, index: number]
  'sort-stops': [area: ThemeArea]
}>()

const areas: Array<{ key: ThemeArea; label: string; showOpacity: boolean }> = [
  { key: 'backdrop', label: '背景板 / 侧边栏', showOpacity: false },
  { key: 'main', label: '主界面', showOpacity: true },
  { key: 'composer', label: '输入栏', showOpacity: true },
  { key: 'control', label: '控件', showOpacity: true },
]
const appearanceModes: Array<{ value: ThemeMode; label: string }> = [
  { value: 'system', label: '跟随系统' },
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
]

const activeArea = ref<ThemeArea | null>(null)
const themeRootEl = ref<HTMLElement | null>(null)
const dialogEl = ref<HTMLElement | null>(null)
const previewEl = ref<InstanceType<typeof ThemePreview> | null>(null)
const areaPopoverEl = ref<HTMLElement | null>(null)
let motionContext: gsap.Context | null = null
let motionMedia: gsap.MatchMedia | null = null
let previewTween: gsap.core.Tween | null = null
let motionEnabled = false

const previewAreaStops = computed<Partial<Record<ThemeArea, ThemeStop[]>>>(() => Object.fromEntries(
  areas.map(({ key }) => [key, props.getStops(key)]),
))
const activeAreaConfig = computed(() => areas.find(({ key }) => key === activeArea.value) ?? null)

function presetTheme(preset: ThemePreset) {
  return themeForMode(preset, props.effectiveThemeMode)
}

function presetBackdropStyle(preset: ThemePreset) {
  const theme = presetTheme(preset)
  return { background: gradientFromStops(theme.backdropAngle ?? 180, theme.backdropStops || [], 1) }
}

function presetMainStyle(preset: ThemePreset) {
  const theme = presetTheme(preset)
  return { background: gradientFromStops(theme.mainAngle ?? 180, theme.mainStops || [], theme.mainOpacity ?? 1) }
}

function presetControlStyle(preset: ThemePreset) {
  const theme = presetTheme(preset)
  return { background: gradientFromStops(theme.controlAngle ?? 180, theme.controlStops || [], theme.controlOpacity ?? 1) }
}

function isPresetActive(preset: ThemePreset) {
  const candidate = presetTheme(preset)
  return areas.every(({ key }) => {
    const stops = candidate[`${key}Stops` as keyof typeof candidate]
    const angle = candidate[`${key}Angle` as keyof typeof candidate]
    const text = candidate[`${key}Text` as keyof typeof candidate]
    const opacity = candidate[`${key}Opacity` as keyof typeof candidate]
    return JSON.stringify(stops) === JSON.stringify(props.getStops(key))
      && angle === props.getAngle(key)
      && text === props.getTextColor(key)
      && (key === 'backdrop' || opacity === props.getOpacity(key))
  })
}

function setThemeMode(mode: ThemeMode) {
  emit('update:theme-mode', mode)
}

function openAreaPopover(area: ThemeArea) {
  activeArea.value = area
}

function closeAreaPopover() {
  activeArea.value = null
}

function animateAreaPopoverEnter(element: Element, done: () => void) {
  const target = element as HTMLElement
  if (!motionEnabled || !motionContext) {
    done()
    return
  }
  const finish = () => {
    gsap.set(target, { clearProps: 'opacity,visibility,transform' })
    done()
  }
  motionContext.add(() => {
    gsap.killTweensOf(target)
    gsap.fromTo(
      target,
      { autoAlpha: 0, y: 8, scale: 0.98, transformOrigin: '50% 45%' },
      { autoAlpha: 1, y: 0, scale: 1, duration: 0.22, ease: 'back.out(1.05)', overwrite: 'auto', onComplete: finish, onInterrupt: finish },
    )
  })
}

function animateAreaPopoverLeave(element: Element, done: () => void) {
  const target = element as HTMLElement
  if (!motionEnabled || !motionContext) {
    done()
    return
  }
  const finish = () => {
    gsap.set(target, { clearProps: 'opacity,visibility,transform' })
    done()
  }
  motionContext.add(() => {
    gsap.killTweensOf(target)
    gsap.fromTo(
      target,
      { autoAlpha: 1, y: 0, scale: 1, transformOrigin: '50% 45%' },
      { autoAlpha: 0, y: 4, scale: 0.985, duration: 0.14, ease: 'power2.in', overwrite: 'auto', onComplete: finish, onInterrupt: finish },
    )
  })
}

function selectPreset(preset: ThemePreset, target: HTMLElement) {
  emit('apply-preset', preset)
  if (!motionEnabled || !motionContext) return
  motionContext.add(() => {
    gsap.fromTo(target, { scale: 0.96, transformOrigin: '50% 50%' }, { scale: 1, duration: 0.22, ease: 'back.out(1.15)', overwrite: 'auto', clearProps: 'transform' })
  })
}

function animatePreviewChange() {
  if (!motionEnabled || !motionContext) return
  const previews = [previewEl.value?.$el].filter((item): item is HTMLElement => item instanceof HTMLElement)
  if (!previews.length) return
  previewTween?.kill()
  motionContext.add(() => {
    previewTween = gsap.fromTo(previews, { autoAlpha: 0.72, scale: 0.992 }, { autoAlpha: 1, scale: 1, duration: 0.26, ease: 'power2.out', overwrite: 'auto', clearProps: 'opacity,visibility,transform' })
  })
}

watch([
  () => props.themePreviewStyle,
  () => props.themePreviewMainStyle,
  () => props.themePreviewComposerStyle,
  () => props.themePreviewControlStyle,
], async () => {
  await nextTick()
  animatePreviewChange()
})

onMounted(() => {
  if (!themeRootEl.value) return
  motionContext = gsap.context(() => {}, themeRootEl.value)
  motionMedia = gsap.matchMedia()
  motionMedia.add('(prefers-reduced-motion: no-preference)', () => {
    motionEnabled = true
    return () => { motionEnabled = false }
  })
})

onUnmounted(() => {
  previewTween?.kill()
  motionMedia?.revert()
  motionContext?.revert()
  previewTween = null
  motionMedia = null
  motionContext = null
})
</script>
