<template>
  <div
    ref="root"
    class="core-model-thinking-menu"
    data-core-model-thinking-menu
    :style="{ '--thinking-color': thinkingColor }"
  >
    <button
      ref="triggerEl"
      class="core-model-thinking-menu__trigger"
      type="button"
      :disabled="disabled"
      aria-haspopup="dialog"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      @click="toggle"
    >
      <span class="core-model-thinking-menu__model">{{ modelLabel }}</span>
      <span class="core-model-thinking-menu__thinking">
        <span class="core-model-thinking-menu__signal" aria-hidden="true" />
        <span class="core-model-thinking-menu__thinking-label">{{ thinkingLabel }}</span>
      </span>
      <ChevronDown class="core-model-thinking-menu__chevron" :size="14" :stroke-width="2" aria-hidden="true" />
      <Brain class="core-model-thinking-menu__compact-icon" :size="16" :stroke-width="2" aria-hidden="true" />
    </button>

    <div
      v-if="open"
      ref="panel"
      popover="manual"
      class="core-model-thinking-menu__panel"
      :style="viewportStyle"
      role="dialog"
      aria-modal="false"
      :aria-label="dialogLabel"
      tabindex="-1"
    >
      <section
        ref="cardEl"
        class="core-model-thinking-menu__card core-model-thinking-menu__card--combined"
        data-model-thinking-card
        :aria-label="dialogLabel"
      >
        <div class="core-model-thinking-menu__body">
          <!-- user:“卡片左上角“模型”两个字不要了”“思考强度和其数值均靠右显示”“还应该有一个栏是组或者供应商的实际名”
               +(顶栏从左到右是分类开关、分组选择器，思考强度与当前等级靠右成组)。 -->
          <header class="core-model-thinking-menu__tools">
            <CoreModelCatalogViewToggle
              class="core-model-thinking-menu__view-toggle"
              :model-value="catalogView"
              @update:model-value="$emit('update:catalogView', $event)"
            />
            <!-- user:“还应该有一个栏是组或者供应商的实际名”“点击后向下展一个卡片 可以选择”+(顶栏的分组选择器，下拉切换当前分组)。 -->
            <div ref="groupPickerEl" class="core-model-thinking-menu__group-picker" data-model-group-picker>
              <button
                class="core-model-thinking-menu__group-trigger"
                type="button"
                aria-haspopup="listbox"
                :aria-expanded="groupMenuOpen"
                :aria-label="t('当前分组：{0}', { 0: activeGroupLabel })"
                @click="toggleGroupMenu"
              >
                <span class="core-model-thinking-menu__group-label">{{ activeGroupLabel }}</span>
                <ChevronDown class="core-model-thinking-menu__group-chevron" :size="13" :stroke-width="2" aria-hidden="true" />
              </button>
              <div v-if="groupMenuOpen" class="core-model-thinking-menu__group-menu" role="listbox" :aria-label="t('模型分组')">
                <button
                  v-for="group in groupSelectOptions"
                  :key="group.key"
                  class="core-model-thinking-menu__group-option"
                  type="button"
                  role="option"
                  :aria-selected="group.key === activeGroupKey ? 'true' : 'false'"
                  :data-model-thinking-group-option="group.key"
                  @click="selectGroup(group)"
                >
                  <span class="core-model-thinking-menu__group-option-label">{{ group.label }}</span>
                  <Check
                    v-if="group.key === activeGroupKey"
                    class="core-model-thinking-menu__check"
                    :size="14"
                    :stroke-width="2.4"
                    aria-hidden="true"
                  />
                </button>
              </div>
            </div>

            <span class="core-model-thinking-menu__thinking-meta">
              <span class="core-model-thinking-menu__column-title">{{ t("思考强度") }}</span>
              <span class="core-model-thinking-menu__current">
                <span class="core-model-thinking-menu__current-dot" aria-hidden="true" />
                <span class="core-model-thinking-menu__current-label">{{ thinkingLabel }}</span>
              </span>
            </span>
          </header>

          <section class="core-model-thinking-menu__model-column" :aria-label="t('模型')">
            <div
              class="core-model-thinking-menu__model-list"
              :aria-label="catalogView === 'group' ? t('组分类的模型') : t('供应商分类的模型')"
            >
              <section class="core-model-thinking-menu__model-group">
                <button
                  v-for="option in displayedModelOptions"
                  :key="option.value"
                  class="core-model-thinking-menu__option"
                  :class="{ 'is-selected': option.value === modelValue, disabled: option.disabled }"
                  type="button"
                  :aria-pressed="option.value === modelValue ? 'true' : 'false'"
                  :disabled="option.disabled"
                  :data-model-thinking-model-option="option.value"
                  @click="selectModel(option)"
                >
                  <span class="core-model-thinking-menu__option-label">{{ option.label }}</span>
                  <Check
                    v-if="option.value === modelValue"
                    class="core-model-thinking-menu__check"
                    :size="14"
                    :stroke-width="2.4"
                    aria-hidden="true"
                  />
                </button>
              </section>
            </div>

            <div v-if="displayedModelOptions.length === 0" class="core-model-thinking-menu__empty">{{ t("暂无可用模型") }}</div>
          </section>

          <aside class="core-model-thinking-menu__thinking-column" :aria-label="t('思考强度')">
            <div v-if="thinkingModeOptions.length" class="core-model-thinking-menu__slider-wrap">
              <ThinkingIntensitySlider
                :model-value="thinkingMode"
                :options="thinkingModeOptions"
                :label="t('思考强度')"
                @update:model-value="selectThinking"
              />
            </div>
            <p v-else class="core-model-thinking-menu__empty-thinking">{{ t("当前模型没有可调的思考等级") }}</p>
          </aside>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { defaultUiText } from '@/i18n/index.ts'

import { t } from '@/i18n/index.ts'

import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { gsap } from 'gsap'
import { Brain, Check, ChevronDown } from 'lucide-vue-next'
import { normalizeCoreThinkingMode, type CoreModelCatalogView, type CoreSelectOption, type CoreThinkingMode, type CoreThinkingModeOption } from '@/composer/execution.ts'
import { thinkingLevelColor } from '@/composer/thinkingPalette.ts'
import CoreModelCatalogViewToggle from '@/components/CoreModelCatalogViewToggle.vue'
import ThinkingIntensitySlider from '@/components/ThinkingIntensitySlider.vue'
import { useComposerMenuMotion } from '@/motion/composerMenu.ts'
import { useComposerMenuViewport } from '@/composables/useComposerMenuViewport.ts'

const props = withDefaults(defineProps<{
  modelValue?: string
  modelOptions?: CoreSelectOption[]
  catalogView?: CoreModelCatalogView
  thinkingMode: CoreThinkingMode | string
  thinkingModeOptions?: CoreThinkingModeOption[]
  shallowThinkingEnabled?: boolean
  modelAriaLabel?: string
  thinkingAriaLabel?: string
  shallowLabel?: string
  disabled?: boolean
}>(), {
  modelValue: '',
  modelOptions: () => [],
  catalogView: 'provider',
  thinkingModeOptions: () => [],
  shallowThinkingEnabled: false,
  modelAriaLabel: '模型',
  thinkingAriaLabel: '思考模式',
  shallowLabel: 'Shallow',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:catalogView': [value: CoreModelCatalogView]
  'update:thinkingMode': [value: string]
  'update:shallowThinkingEnabled': [value: boolean]
}>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const triggerEl = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const cardEl = ref<HTMLElement | null>(null)
const groupMenuOpen = ref(false)
const groupPickerEl = ref<HTMLElement | null>(null)
const activeGroupKey = ref('')

const { animatePrimaryCard, cancel } = useComposerMenuMotion(root)
const { updateViewportPosition, viewportStyle } = useComposerMenuViewport(root, panel)
const reducedMotion = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
  : true
let leaveTween: gsap.core.Tween | null = null
let closing = false

const modelLabel = computed(() => {
  const option = props.modelOptions.find((item) => item.value === props.modelValue)
  return option?.selectedLabel || option?.label || defaultUiText(props.modelAriaLabel, "模型")
})

const modelOptionGroups = computed(() => {
  const groups = new Map<string, { key: string; label: string; options: CoreSelectOption[] }>()
  for (const option of props.modelOptions) {
    const label = option.group?.trim() || t("默认模型")
    const key = option.groupKey?.trim() || `label:${label}`
    const options = groups.get(key)?.options || []
    options.push(option)
    groups.set(key, { key, label, options })
  }
  return [...groups.values()]
})

// user:“组里面应该再加一个全部，和其他，供应商里应该加一个全部”“有组的时候只展示对应组或供应商的模型的就行了”
// (分组选择器提供全部/其他，列表只展示当前选择对应的模型)。
const ALL_GROUP_KEY = '__all__'
const OTHER_GROUP_KEY = '__other__'
const DEFAULT_GROUP_KEY = 'default'
const UNGROUPED_GROUP_KEY = 'group:__ungrouped__'

const namedModelGroups = computed(() => modelOptionGroups.value.filter(
  (group) => group.key !== DEFAULT_GROUP_KEY && group.key !== UNGROUPED_GROUP_KEY,
))

const otherModelOptions = computed(() => props.modelOptions.filter((option) => {
  const key = option.groupKey?.trim()
  return !key || !option.group?.trim() || key === DEFAULT_GROUP_KEY || key === UNGROUPED_GROUP_KEY
}))

const groupSelectOptions = computed(() => {
  const all = { key: ALL_GROUP_KEY, label: t("全部") }
  if (props.catalogView === 'group') {
    return [
      all,
      ...namedModelGroups.value.map((group) => ({ key: group.key, label: group.label })),
      { key: OTHER_GROUP_KEY, label: t("其他") },
    ]
  }
  return [
    all,
    ...modelOptionGroups.value
      .filter((group) => group.key !== DEFAULT_GROUP_KEY)
      .map((group) => ({ key: group.key, label: group.label })),
  ]
})

const displayedModelOptions = computed(() => {
  if (activeGroupKey.value === ALL_GROUP_KEY) {
    return modelOptionGroups.value.flatMap((group) => group.options)
  }
  if (activeGroupKey.value === OTHER_GROUP_KEY) return otherModelOptions.value
  return modelOptionGroups.value.find((group) => group.key === activeGroupKey.value)?.options ?? []
})

const activeGroupLabel = computed(() => (
  groupSelectOptions.value.find((option) => option.key === activeGroupKey.value)?.label || t("全部")
))

function groupKeyForModel(value: string): string {
  const group = modelOptionGroups.value.find((item) => item.options.some((option) => option.value === value))
  if (!group) return ''
  if (props.catalogView === 'group' && (group.key === DEFAULT_GROUP_KEY || group.key === UNGROUPED_GROUP_KEY)) {
    return OTHER_GROUP_KEY
  }
  if (group.key === DEFAULT_GROUP_KEY) return ALL_GROUP_KEY
  return group.key
}

watch(
  [modelOptionGroups, () => props.catalogView],
  ([groups]) => {
    if (!groups.length) {
      activeGroupKey.value = ALL_GROUP_KEY
      return
    }
    if (groupSelectOptions.value.some((option) => option.key === activeGroupKey.value)) return
    activeGroupKey.value = groupKeyForModel(props.modelValue) || ALL_GROUP_KEY
  },
  { immediate: true },
)

watch(
  () => props.modelValue,
  () => {
    if (activeGroupKey.value === ALL_GROUP_KEY || activeGroupKey.value === OTHER_GROUP_KEY) return
    const key = groupKeyForModel(props.modelValue)
    if (key) activeGroupKey.value = key
  },
)

const thinkingLabel = computed(() => {
  const option = props.thinkingModeOptions.find((item) => item.value === props.thinkingMode)
  return option?.label || (normalizeCoreThinkingMode(props.thinkingMode, 'off') === 'off'
    ? defaultUiText(props.thinkingAriaLabel, "思考模式")
    : normalizeCoreThinkingMode(props.thinkingMode, 'off'))
})

const thinkingColor = computed(() => thinkingLevelColor(props.thinkingMode))
const ariaLabel = computed(() => t("模型与思考强度：{0} {1}", { 0: modelLabel.value, 1: thinkingLabel.value }))
const dialogLabel = computed(() => t("模型与思考强度"))

function toggle(): void {
  if (props.disabled) return
  if (open.value) {
    close(true)
    return
  }
  leaveTween?.kill()
  leaveTween = null
  closing = false
  groupMenuOpen.value = false
  open.value = true
  void nextTick(() => {
    panel.value?.showPopover?.()
    updateViewportPosition()
    panel.value?.focus({ preventScroll: true })
    animatePrimaryCard(
      cardEl.value,
      ':scope > .core-model-thinking-menu__body > .core-model-thinking-menu__model-column, :scope > .core-model-thinking-menu__body > .core-model-thinking-menu__thinking-column',
    )
    scrollSelectedModel()
  })
}

function close(returnFocus = false): void {
  if (!open.value || closing) return
  cancel()
  const card = cardEl.value
  const finish = (): void => {
    open.value = false
    closing = false
    groupMenuOpen.value = false
    panel.value?.hidePopover?.()
    leaveTween = null
    if (returnFocus) triggerEl.value?.focus({ preventScroll: true })
  }
  const canAnimate = !reducedMotion && !!card && card.getBoundingClientRect().height > 0
  if (!canAnimate) {
    finish()
    return
  }
  closing = true
  leaveTween?.kill()
  leaveTween = gsap.to(card, {
    autoAlpha: 0,
    y: 6,
    scale: 0.985,
    duration: 0.16,
    ease: 'power2.in',
    onComplete: finish,
  })
}

function selectModel(option: CoreSelectOption): void {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  void nextTick(scrollSelectedModel)
}

function selectThinking(value: string): void {
  emit('update:thinkingMode', value)
}

function toggleGroupMenu(): void {
  if (!modelOptionGroups.value.length) return
  groupMenuOpen.value = !groupMenuOpen.value
}

function selectGroup(group: { key: string }): void {
  activeGroupKey.value = group.key
  groupMenuOpen.value = false
  void nextTick(() => {
    const list = cardEl.value?.querySelector<HTMLElement>('.core-model-thinking-menu__model-list')
    if (list) list.scrollTop = 0
  })
}

function scrollSelectedModel(): void {
  const list = cardEl.value?.querySelector<HTMLElement>('.core-model-thinking-menu__model-list')
  const selected = list?.querySelector<HTMLElement>('.core-model-thinking-menu__option.is-selected')
  if (!list || !selected) return
  const listRect = list.getBoundingClientRect()
  const rowRect = selected.getBoundingClientRect()
  if (!listRect.height || !rowRect.height) return
  if (rowRect.top < listRect.top) list.scrollTop -= listRect.top - rowRect.top
  else if (rowRect.bottom > listRect.bottom) list.scrollTop += rowRect.bottom - listRect.bottom
}

function onPointerDown(event: PointerEvent): void {
  const target = event.target as Node | null
  if (!target) return
  if (groupMenuOpen.value && groupPickerEl.value && !groupPickerEl.value.contains(target)) {
    groupMenuOpen.value = false
  }
  if (!root.value || root.value.contains(target)) return
  close(false)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (groupMenuOpen.value) {
    groupMenuOpen.value = false
    return
  }
  if (open.value) close(true)
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeydown)
  leaveTween?.kill()
  leaveTween = null
  cancel()
})

</script>

<style scoped>
.core-model-thinking-menu {
  position: relative;
  min-width: 0;
  flex: 0 1 auto;
  --text: var(--theme-composer-text);
}

.core-model-thinking-menu__trigger {
  min-width: 0;
  max-width: min(250px, 46vw);
  height: 28px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  background: transparent;
  color: color-mix(in srgb, var(--text) 88%, transparent);
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.core-model-thinking-menu__trigger:hover,
.core-model-thinking-menu__trigger[aria-expanded='true'] {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.core-model-thinking-menu__trigger[aria-expanded='true'] {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-model-thinking-menu__trigger:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 28%, transparent);
  outline-offset: 2px;
}

.core-model-thinking-menu__model {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.core-model-thinking-menu__thinking {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-weight: 600;
}

.core-model-thinking-menu__thinking-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-model-thinking-menu__signal,
.core-model-thinking-menu__current-dot {
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--thinking-color);
  box-shadow: 0 0 7px color-mix(in srgb, var(--thinking-color) 55%, transparent);
  transition:
    background-color var(--dur-base) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

.core-model-thinking-menu__chevron {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 58%, transparent);
}

.core-model-thinking-menu__compact-icon {
  display: none;
  color: var(--thinking-color);
}

.core-model-thinking-menu__panel {
  --text: var(--theme-composer-text);
  position: fixed;
  inset: auto;
  left: var(--composer-menu-left);
  top: var(--composer-menu-top, auto);
  bottom: var(--composer-menu-bottom, auto);
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  overflow: visible;
  z-index: var(--z-popover, 60);
  width: max-content;
  max-width: calc(100vw - 24px);
  color: var(--text);
  transform: none;
  transform-origin: bottom center;
}

.core-model-thinking-menu__panel:focus {
  outline: none;
}

.core-model-thinking-menu__panel[data-placement='below'] {
  transform-origin: top center;
}

/* user:“结构紧凑一点，让卡片的体积小一些”+(卡片从 464×404 收到 384×312，同一条顶栏承载分类和思考强度)。 */
.core-model-thinking-menu__card {
  box-sizing: border-box;
  width: min(384px, calc(100vw - 24px));
  height: min(312px, var(--composer-menu-max-height, 312px));
  padding: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-radius: var(--radius-lg);
  background: var(--theme-composer-background);
  box-shadow: var(--shadow-md);
  color: var(--text);
  transform-origin: bottom center;
}

.core-model-thinking-menu__panel[data-placement='below'] .core-model-thinking-menu__card {
  transform-origin: top center;
}

.core-model-thinking-menu__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 30px;
  grid-template-rows: 38px minmax(0, 1fr);
  grid-template-areas:
    'tools tools'
    'models thinking';
  gap: 0 var(--space-2);
  height: 100%;
  min-height: 0;
}

.core-model-thinking-menu__tools {
  grid-area: tools;
  position: relative;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  padding: 0 2px;
}

/* user:“点击后向下展一个卡片 可以选择”+(点开分组选择器时在顶栏下方展开一张圆角小卡)。 */
.core-model-thinking-menu__group-picker {
  position: relative;
  flex: 0 1 auto;
  min-width: 0;
}

.core-model-thinking-menu__group-trigger {
  max-width: 136px;
  height: 26px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  background: color-mix(in srgb, var(--text) 6%, transparent);
  color: color-mix(in srgb, var(--text) 80%, transparent);
  font: inherit;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

.core-model-thinking-menu__group-trigger:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.core-model-thinking-menu__group-trigger:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 28%, transparent);
  outline-offset: 1px;
}

.core-model-thinking-menu__group-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-model-thinking-menu__group-chevron {
  flex: none;
  opacity: 0.65;
  transition: transform var(--dur-base) var(--ease-out);
}

.core-model-thinking-menu__group-trigger[aria-expanded='true'] .core-model-thinking-menu__group-chevron {
  transform: rotate(180deg);
}

.core-model-thinking-menu__group-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 10;
  min-width: 176px;
  max-width: 224px;
  max-height: 232px;
  overflow-y: auto;
  display: grid;
  gap: 2px;
  padding: var(--space-1);
  border: 1px solid color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-radius: var(--radius);
  background: var(--theme-composer-background);
  box-shadow: var(--shadow-md);
}

.core-model-thinking-menu__group-option {
  min-height: 30px;
  padding: 2px var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 11.5px;
  text-align: left;
  cursor: pointer;
}

.core-model-thinking-menu__group-option:hover,
.core-model-thinking-menu__group-option[aria-selected='true'] {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.core-model-thinking-menu__group-option-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* user:“思考强度和其数值均靠右显示”+(标题与当前等级作为一组贴在卡片右上角)。 */
.core-model-thinking-menu__thinking-meta {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.core-model-thinking-menu__model-column {
  grid-area: models;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.core-model-thinking-menu__column-title {
  flex: none;
  color: color-mix(in srgb, var(--text) 60%, transparent);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.03em;
}

.core-model-thinking-menu__view-toggle {
  flex: 0 0 auto;
}

.core-model-thinking-menu__model-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-gutter: stable;
}

.core-model-thinking-menu__model-group {
  display: grid;
  gap: var(--space-1);
}

.core-model-thinking-menu__model-group + .core-model-thinking-menu__model-group {
  margin-top: var(--space-1);
}

.core-model-thinking-menu__option {
  box-sizing: border-box;
  width: 100%;
  min-height: 30px;
  padding: 2px var(--space-2);
  border: 0;
  border-radius: 0;
  position: relative;
  z-index: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}

/* user:“各种地方该加圆角加圆角”+(模型行的高亮也收成圆角块，不再用左右渐隐的硬长条)。 */
.core-model-thinking-menu__option::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  border-radius: var(--radius-sm);
  opacity: 0;
  pointer-events: none;
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.core-model-thinking-menu__option:hover::before {
  opacity: 1;
}

.core-model-thinking-menu__option.is-selected::before {
  opacity: 1;
}

.core-model-thinking-menu__option.is-selected:hover::before {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-model-thinking-menu__option > * {
  position: relative;
  z-index: 1;
}

.core-model-thinking-menu__option-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-model-thinking-menu__option.disabled,
.core-model-thinking-menu__option:disabled {
  opacity: 0.42;
  cursor: default;
}

.core-model-thinking-menu__check {
  flex: 0 0 auto;
  color: var(--green);
  animation: choose-pop var(--dur-slow) cubic-bezier(0.34, 1.56, 0.64, 1);
}

.core-model-thinking-menu__empty,
.core-model-thinking-menu__empty-thinking {
  padding: var(--space-2);
  color: color-mix(in srgb, var(--text) 50%, transparent);
  font-size: 11px;
}

/* user:“条紧邻模型的滚动条那里”+(思考列只剩轨道和节点，紧贴模型列表右缘)。 */
.core-model-thinking-menu__thinking-column {
  grid-area: thinking;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.core-model-thinking-menu__current {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  padding: 3px var(--space-2);
  border-radius: 999px;
  background: color-mix(in srgb, var(--text) 6%, transparent);
  color: color-mix(in srgb, var(--text) 82%, transparent);
  font-size: 11px;
  font-weight: 650;
}

.core-model-thinking-menu__current-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-model-thinking-menu__slider-wrap {
  display: flex;
  flex: 1;
  min-height: 0;
}

@keyframes choose-pop {
  from {
    opacity: 0;
    transform: scale(0.55);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@container composer (max-width: 480px) {
  .core-model-thinking-menu__trigger {
    width: 28px;
    padding: 0;
    justify-content: center;
  }

  .core-model-thinking-menu__model,
  .core-model-thinking-menu__thinking,
  .core-model-thinking-menu__chevron {
    display: none;
  }

  .core-model-thinking-menu__compact-icon {
    display: block;
  }
}

@media (prefers-reduced-motion: reduce) {
  .core-model-thinking-menu__check,
  .core-model-thinking-menu__group-chevron {
    animation: none;
    transition: none;
  }
}
</style>
