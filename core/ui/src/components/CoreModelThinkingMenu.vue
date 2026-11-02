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
      <!-- user:“将鼠标悬浮在思考等级上的时候 只悬浮一个条调节思考等级在上方”
           +(悬浮在思考等级上时，卡片滑条放倒成悬浮条浮到按钮上方)。 -->
      <span
        ref="thinkingEl"
        class="core-model-thinking-menu__thinking"
        @pointerenter="activateHover"
        @pointerleave="scheduleHoverHide"
      >
        <span class="core-model-thinking-menu__signal" aria-hidden="true" />
        <span class="core-model-thinking-menu__thinking-label">{{ thinkingLabel }}</span>
      </span>
      <ChevronDown class="core-model-thinking-menu__chevron" :size="14" :stroke-width="2" aria-hidden="true" />
      <Brain class="core-model-thinking-menu__compact-icon" :size="16" :stroke-width="2" aria-hidden="true" />
    </button>

    <div
      v-if="open || hoverMode"
      ref="panel"
      popover="manual"
      class="core-model-thinking-menu__panel"
      :class="{ 'is-hover-preview': hoverMode && !open }"
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
            <div
              v-if="thinkingModeOptions.length"
              ref="sliderWrapEl"
              class="core-model-thinking-menu__slider-wrap"
              :class="{ 'is-laid': hoverMode && !open }"
              @pointerenter="cancelHoverHide"
              @pointerleave="scheduleHoverHide"
            >
              <ThinkingIntensitySlider
                :model-value="thinkingMode"
                :options="thinkingModeOptions"
                :label="t('思考强度')"
                :show-particles="particlesOn"
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

// user:“悬浮条是你要实现的”“我不建议你单独做一个悬浮条，而是直接用卡片右侧的那个思考等级把它给放倒”
// +(悬浮态复用卡片右列的思考强度滑条本体：整卡隐藏、只把滑条放倒 90° 摆到触发按钮上方，不新建组件)。
const hoverMode = ref(false)
const thinkingEl = ref<HTMLElement | null>(null)
const sliderWrapEl = ref<HTMLElement | null>(null)
let flightTimeline: gsap.core.Timeline | null = null
let hoverHideTween: gsap.core.Tween | null = null
let hoverHideTimer = 0
const HOVER_HIDE_DELAY = 140
// user:“那个max模式下的粒子特效出现时机延后，等到这个条滑块的位置已经固定下来了，再出现粒子特效”
// +(飞入期间关闭滑条粒子，落位固定后再开启)。
const particlesOn = ref(true)

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

// 面板在悬浮预览与展开两种状态下都会挂载，挂载时统一弹到顶层并按触发按钮定位。
watch(panel, (el) => {
  if (!el) return
  el.showPopover?.()
  updateViewportPosition()
})

// user:“将鼠标悬浮在思考等级上的时候 只悬浮一个条调节思考等级在上方”
// +(悬浮思考等级：整卡隐藏，滑条放倒 90° 悬浮到按钮上方，可直接调级)。
function activateHover(): void {
  cancelHoverHide()
  hoverHideTween?.kill()
  hoverHideTween = null
  const wrap = sliderWrapEl.value
  if (wrap && hoverMode.value) {
    gsap.set(wrap, { autoAlpha: 1 })
    return
  }
  if (open.value || props.disabled || !props.thinkingModeOptions.length) return
  hoverMode.value = true
  void nextTick(() => {
    updateViewportPosition()
    void nextTick(applyHoverPose)
  })
}

// 放倒姿态：绕滑轨端头的圆心摆放（悬浮时端头在左、立起后端头在下，同一个圆），
// 顶部档位朝右；开卡时把 rotation 归 0 即为用户要的“逆时针旋转 90 度”。
// user:“旋转的圆心应该是绕着那个条最左侧，也就是左边或者竖着下边的那个圆的圆心，而不是绝对的圆心”
// +(transformOrigin 取轨道端头圆心，位移也让端头圆心对准悬浮位置，旋转像绕端头甩动)。
// user:“悬浮状态下调小一点”+(悬浮时滑轨实际收短，起飞前按恢复全长后的滑轨重新摆位，视觉位置保持不变)。
function applyLaidPose(wrap: HTMLElement): void {
  // 先归位再测量，避免上一次姿态的位移污染几何测量。
  gsap.set(wrap, { x: 0, y: 0, rotation: 0 })
  const rail = wrap.querySelector<HTMLElement>('.sunday-thinking-slider__rail')
  const track = wrap.querySelector<HTMLElement>('.sunday-thinking-slider__track')
  const spanRect = thinkingEl.value?.getBoundingClientRect()
  const triggerRect = triggerEl.value?.getBoundingClientRect()
  if (!rail || !spanRect || !triggerRect || !triggerRect.height) return
  const wrapRect = wrap.getBoundingClientRect()
  const railRect = rail.getBoundingClientRect()
  if (!railRect.height) return
  const length = railRect.height
  const thickness = railRect.width
  const capRadius = track ? track.getBoundingClientRect().width / 2 : thickness / 2
  const margin = 8
  const gap = 10
  const centerX = Math.min(
    Math.max(spanRect.left + spanRect.width / 2, margin + length / 2),
    window.innerWidth - margin - length / 2,
  )
  const centerY = Math.max(margin + thickness / 2, triggerRect.top - gap - thickness / 2)
  const originX = railRect.left + railRect.width / 2 - wrapRect.left
  const originY = railRect.bottom - capRadius - wrapRect.top
  gsap.set(wrap, {
    transformOrigin: `${originX}px ${originY}px`,
    x: centerX - length / 2 + capRadius - (railRect.left + railRect.width / 2),
    y: centerY - (railRect.bottom - capRadius),
    rotation: 90,
  })
}

function applyHoverPose(): void {
  const wrap = sliderWrapEl.value
  if (!wrap || open.value || !hoverMode.value) return
  applyLaidPose(wrap)
}

function scheduleHoverHide(): void {
  if (!hoverMode.value || open.value) return
  window.clearTimeout(hoverHideTimer)
  hoverHideTimer = window.setTimeout(finishHoverHide, HOVER_HIDE_DELAY)
}

function cancelHoverHide(): void {
  window.clearTimeout(hoverHideTimer)
}

function finishHoverHide(): void {
  cancelHoverHide()
  const wrap = sliderWrapEl.value
  if (!wrap) {
    hoverMode.value = false
    return
  }
  if (reducedMotion) {
    clearHoverPose()
    return
  }
  hoverHideTween?.kill()
  hoverHideTween = gsap.to(wrap, {
    autoAlpha: 0,
    duration: 0.12,
    ease: 'power2.in',
    onComplete: clearHoverPose,
  })
}

function clearHoverPose(): void {
  cancelHoverHide()
  hoverHideTween?.kill()
  hoverHideTween = null
  const wrap = sliderWrapEl.value
  if (wrap) gsap.set(wrap, { clearProps: 'all' })
  hoverMode.value = false
}

function resetFlightProps(): void {
  const card = cardEl.value
  const targets = [
    sliderWrapEl.value,
    card,
    card?.querySelector<HTMLElement>('.core-model-thinking-menu__tools'),
    card?.querySelector<HTMLElement>('.core-model-thinking-menu__model-column'),
  ].filter(Boolean) as HTMLElement[]
  if (targets.length) gsap.set(targets, { clearProps: 'all' })
  // clearProps 对 CSS 自定义属性不保证移除，显式删掉让 ::before 回到默认全显。
  card?.style.removeProperty('--thinking-card-reveal')
  particlesOn.value = true
}

// user:“旋转的圆心应该是绕着那个条最左侧，也就是左边或者竖着下边的那个圆的圆心”
// +(绕端头圆心逆时针转正)。
// user:“向右滑动的过程中，把这个卡片给划出来”“转正后悬浮条平移过去”“下一步就是转正和平移同时进行”
// +(转正与平移合成同一段进行，卡片在这段运动中同步被划出，滑条落位即到位)。
function playOpenFlight(): void {
  const wrap = sliderWrapEl.value
  const card = cardEl.value
  if (!wrap || !card) return
  const header = card.querySelector<HTMLElement>('.core-model-thinking-menu__tools')
  const modelColumn = card.querySelector<HTMLElement>('.core-model-thinking-menu__model-column')
  flightTimeline?.kill()
  particlesOn.value = false
  // 悬浮条比卡内滑轨短：类名移除、全长恢复后，按新几何重新摆位再起飞，避免尺寸跳变。
  applyLaidPose(wrap)
  // 卡片底板挪到 ::before 上用自定义变量控制显现，飞行中的滑条本体不受卡片透明度/裁切影响。
  if (header) gsap.set(header, { autoAlpha: 0, y: 4 })
  if (modelColumn) gsap.set(modelColumn, { clipPath: 'inset(0% 100% 0% 0%)' })
  gsap.set(card, { '--thinking-card-reveal': 0 })
  const timeline = gsap.timeline({ defaults: { overwrite: 'auto' }, onComplete: resetFlightProps })
  flightTimeline = timeline
  timeline
    .to(wrap, { rotation: 0, x: 0, y: 0, duration: 0.34, ease: 'power3.inOut' })
    .to(card, { '--thinking-card-reveal': 1, duration: 0.34, ease: 'power2.out' }, 0.04)
  if (modelColumn) {
    timeline.to(modelColumn, { clipPath: 'inset(0% 0% 0% 0%)', duration: 0.34, ease: 'power2.out' }, 0.04)
  }
  if (header) {
    timeline.to(header, { autoAlpha: 1, y: 0, duration: 0.24, ease: 'power2.out' }, 0.14)
  }
}

function toggle(): void {
  if (props.disabled) return
  if (open.value) {
    close(true)
    return
  }
  const fromHover = hoverMode.value
  hoverMode.value = false
  cancelHoverHide()
  leaveTween?.kill()
  leaveTween = null
  closing = false
  groupMenuOpen.value = false
  open.value = true
  void nextTick(() => {
    updateViewportPosition()
    panel.value?.focus({ preventScroll: true })
    if (fromHover && !reducedMotion) {
      playOpenFlight()
    } else {
      if (fromHover) clearHoverPose()
      animatePrimaryCard(
        cardEl.value,
        ':scope > .core-model-thinking-menu__body > .core-model-thinking-menu__model-column, :scope > .core-model-thinking-menu__body > .core-model-thinking-menu__thinking-column',
      )
    }
    scrollSelectedModel()
  })
}

function close(returnFocus = false): void {
  if (!open.value || closing) return
  cancel()
  flightTimeline?.kill()
  flightTimeline = null
  resetFlightProps()
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
  if (open.value) {
    close(true)
    return
  }
  if (hoverMode.value) clearHoverPose()
}

function onWindowResize(): void {
  if (!open.value && hoverMode.value) clearHoverPose()
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onWindowResize)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onWindowResize)
  window.clearTimeout(hoverHideTimer)
  hoverHideTween?.kill()
  hoverHideTween = null
  flightTimeline?.kill()
  flightTimeline = null
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
  position: relative;
  width: min(384px, calc(100vw - 24px));
  height: min(312px, var(--composer-menu-max-height, 312px));
  padding: var(--space-2);
  color: var(--text);
  transform-origin: bottom center;
}

/* user:“向右滑动的过程中，把这个卡片给划出来”
   +(底板移到 ::before 并用 --thinking-card-reveal 控制显现：
   飞入时底板从左缘向右“划”开，飞行中的滑条本体不受卡片裁切/透明度影响)。
   user:“为什么前面那个面板没有模糊”“修”+(底板不能只有半透明底色，
   要跟其它浮层一样挂毛玻璃滤镜，否则背后资源卡的文字会原样透出来)。 */
.core-model-thinking-menu__card::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  border: 1px solid color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-radius: var(--radius-lg);
  background: var(--theme-composer-background);
  -webkit-backdrop-filter: var(--optical-glass-filter);
  backdrop-filter: var(--optical-glass-filter);
  box-shadow: var(--shadow-md);
  opacity: var(--thinking-card-reveal, 1);
  transform: scaleX(calc(0.9 + 0.1 * var(--thinking-card-reveal, 1)));
  transform-origin: left center;
  pointer-events: none;
}

.core-model-thinking-menu__panel[data-placement='below'] .core-model-thinking-menu__card {
  transform-origin: top center;
}

.core-model-thinking-menu__body {
  position: relative;
  z-index: 1;
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

/* user:“悬浮的时候只露出那一条”+(悬浮预览态整卡不可见、不拦截输入，只有放倒的滑条可交互)。 */
.core-model-thinking-menu__panel.is-hover-preview {
  pointer-events: none;
}

.core-model-thinking-menu__panel.is-hover-preview .core-model-thinking-menu__card {
  visibility: hidden;
}

/* user:“悬浮状态下调小一点”+(悬浮时放倒的滑轨实际收短到 180px，落位后恢复卡内全长)。 */
.core-model-thinking-menu__panel.is-hover-preview .core-model-thinking-menu__slider-wrap {
  visibility: visible;
  pointer-events: auto;
  flex: 0 0 auto;
  height: 180px;
}

/* user:“再给 hover 时的那个思考条加一个低透玻璃的胶囊样式包裹住它”
   +(悬浮条外套一层低透过率的磨砂玻璃胶囊：半透明主题底色 + 背景模糊 + 细边与柔影，
   随滑条一起放倒平移，卡片展开后不出现)。 */
.core-model-thinking-menu__panel.is-hover-preview .core-model-thinking-menu__slider-wrap {
  position: relative;
}

.core-model-thinking-menu__panel.is-hover-preview .core-model-thinking-menu__slider-wrap::before {
  content: '';
  position: absolute;
  inset: -6px;
  z-index: 0;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-composer-background) 60%, transparent);
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, #fff 8%, transparent),
    0 8px 22px color-mix(in srgb, #000 16%, transparent);
  backdrop-filter: blur(16px) saturate(1.2);
  -webkit-backdrop-filter: blur(16px) saturate(1.2);
  pointer-events: none;
}

.core-model-thinking-menu__slider-wrap.is-laid :deep(.sunday-thinking-slider__body) {
  cursor: ew-resize;
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

/* user:“为什么前面那个面板没有模糊”“修”+(分组下拉同属浮层，底色也要配毛玻璃)。 */
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
  -webkit-backdrop-filter: var(--optical-glass-filter);
  backdrop-filter: var(--optical-glass-filter);
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
