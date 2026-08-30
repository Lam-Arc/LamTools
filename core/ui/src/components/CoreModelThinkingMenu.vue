<template>
  <div ref="root" class="core-model-thinking-menu" data-core-model-thinking-menu>
    <button
      class="core-model-thinking-menu__trigger"
      type="button"
      :disabled="disabled"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      @click="toggle"
    >
      <span class="core-model-thinking-menu__model">{{ modelLabel }}</span>
      <span class="core-model-thinking-menu__thinking">{{ thinkingLabel }}</span>
      <ChevronDown class="core-model-thinking-menu__chevron" :size="14" :stroke-width="2" aria-hidden="true" />
    </button>

    <div v-if="open" class="core-model-thinking-menu__panel" role="menu">
      <section ref="parameterCard" class="core-model-thinking-menu__card core-model-thinking-menu__card--parameters" aria-label="模型与思考参数">
        <button
          class="core-model-thinking-menu__option core-model-thinking-menu__parameter"
          type="button"
          role="menuitem"
          aria-haspopup="menu"
          :aria-expanded="activeSection === 'model'"
          data-model-thinking-section="model"
          @mouseenter="activateSection('model')"
          @focus="activateSection('model')"
          @click="activateSection('model')"
        >
          <span class="core-model-thinking-menu__parameter-label">模型</span>
          <span class="core-model-thinking-menu__parameter-value">{{ modelLabel }}</span>
          <ChevronRight class="core-model-thinking-menu__parameter-chevron" :size="15" :stroke-width="2" aria-hidden="true" />
        </button>
        <button
          class="core-model-thinking-menu__option core-model-thinking-menu__parameter"
          type="button"
          role="menuitem"
          aria-haspopup="menu"
          :aria-expanded="activeSection === 'thinking'"
          data-model-thinking-section="thinking"
          @mouseenter="activateSection('thinking')"
          @focus="activateSection('thinking')"
          @click="activateSection('thinking')"
        >
          <span class="core-model-thinking-menu__parameter-label">思考等级</span>
          <span class="core-model-thinking-menu__parameter-value">{{ thinkingLabel }}</span>
          <ChevronRight class="core-model-thinking-menu__parameter-chevron" :size="15" :stroke-width="2" aria-hidden="true" />
        </button>
      </section>

      <section
        v-if="activeSection === 'model'"
        ref="submenuCard"
        class="core-model-thinking-menu__card core-model-thinking-menu__card--submenu"
        :class="'core-model-thinking-menu__card--submenu-' + submenuSide"
        role="menu"
        aria-label="模型选项"
        data-model-thinking-submenu="model"
      >
        <div class="core-model-thinking-menu__model-list" aria-label="按供应商分组的模型">
          <section
            v-for="group in modelOptionGroups"
            :key="group.label"
            class="core-model-thinking-menu__model-group"
            role="group"
            :aria-label="group.label"
          >
            <div class="core-model-thinking-menu__provider">{{ group.label }}</div>
            <button
              v-for="option in group.options"
              :key="option.value"
              class="core-model-thinking-menu__option"
              :class="{ active: option.value === modelValue, disabled: option.disabled }"
              type="button"
              role="menuitemradio"
              :aria-checked="option.value === modelValue"
              :disabled="option.disabled"
              :data-model-thinking-model-option="option.value"
              @click="selectModel(option)"
            >
              <span>{{ option.label }}</span>
              <span v-if="option.value === modelValue" class="core-model-thinking-menu__check" aria-hidden="true">✓</span>
            </button>
          </section>
        </div>
        <div v-if="modelOptions.length === 0" class="core-model-thinking-menu__empty">暂无可用模型</div>
      </section>

      <section
        v-else-if="activeSection === 'thinking'"
        ref="submenuCard"
        class="core-model-thinking-menu__card core-model-thinking-menu__card--submenu"
        :class="'core-model-thinking-menu__card--submenu-' + submenuSide"
        role="menu"
        aria-label="思考等级选项"
        data-model-thinking-submenu="thinking"
      >
        <div class="core-model-thinking-menu__heading">思考等级</div>
        <button
          v-for="option in thinkingModeOptions"
          :key="option.value"
          class="core-model-thinking-menu__option"
          :class="{ active: option.value === thinkingMode }"
          type="button"
          role="menuitemradio"
          :aria-checked="option.value === thinkingMode"
          :data-model-thinking-level-option="option.value"
          @click="selectThinking(option.value)"
        >
          <span>{{ option.label }}</span>
          <span v-if="option.value === thinkingMode" class="core-model-thinking-menu__check" aria-hidden="true">✓</span>
        </button>
        <button
          class="core-model-thinking-menu__option core-model-thinking-menu__shallow"
          :class="{ active: shallowThinkingEnabled }"
          type="button"
          role="menuitemcheckbox"
          :aria-checked="shallowThinkingEnabled"
          data-model-thinking-shallow-option
          @click="toggleShallow"
        >
          <span>{{ shallowLabel }}</span>
          <span v-if="shallowThinkingEnabled" class="core-model-thinking-menu__check" aria-hidden="true">✓</span>
        </button>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import { coreModelDisplayLabel, normalizeCoreThinkingMode, type CoreSelectOption, type CoreThinkingMode, type CoreThinkingModeOption } from '../composer/execution'

const props = withDefaults(defineProps<{
  modelValue?: string
  modelOptions?: CoreSelectOption[]
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
  thinkingModeOptions: () => [],
  shallowThinkingEnabled: false,
  modelAriaLabel: '模型',
  thinkingAriaLabel: '思考模式',
  shallowLabel: 'Shallow',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:thinkingMode': [value: string]
  'update:shallowThinkingEnabled': [value: boolean]
}>()

const open = ref(false)
const activeSection = ref<'model' | 'thinking' | null>(null)
const submenuSide = ref<'left' | 'right'>('right')
const root = ref<HTMLElement | null>(null)
const parameterCard = ref<HTMLElement | null>(null)
const submenuCard = ref<HTMLElement | null>(null)

const modelLabel = computed(() => {
  const option = props.modelOptions.find((item) => item.value === props.modelValue)
  return option?.selectedLabel || option?.label || props.modelAriaLabel
})

const modelOptionGroups = computed(() => {
  const groups = new Map<string, CoreSelectOption[]>()
  for (const option of props.modelOptions) {
    const label = option.group?.trim() || '默认模型'
    const options = groups.get(label) || []
    options.push(option)
    groups.set(label, options)
  }
  return [...groups].map(([label, options]) => ({ label, options }))
})

const thinkingLabel = computed(() => {
  const option = props.thinkingModeOptions.find((item) => item.value === props.thinkingMode)
  return option?.label || (props.thinkingMode === 'none' ? props.thinkingAriaLabel : normalizeCoreThinkingMode(props.thinkingMode, 'none'))
})

const ariaLabel = computed(() => `模型与思考强度：${modelLabel.value} ${thinkingLabel.value}`)

function toggle(): void {
  if (props.disabled) return
  open.value = !open.value
  activeSection.value = null
}

function activateSection(section: 'model' | 'thinking'): void {
  activeSection.value = section
  void nextTick(updateSubmenuSide)
}

function updateSubmenuSide(): void {
  if (!parameterCard.value || !submenuCard.value) return
  const mainRect = parameterCard.value.getBoundingClientRect()
  const submenuWidth = submenuCard.value.getBoundingClientRect().width
  const spaceValue = getComputedStyle(parameterCard.value).getPropertyValue('--space-2')
  const gap = Number.parseFloat(spaceValue) || 8
  const required = submenuWidth + gap
  const roomLeft = mainRect.left
  const roomRight = window.innerWidth - mainRect.right

  if (roomRight >= required) submenuSide.value = 'right'
  else if (roomLeft >= required) submenuSide.value = 'left'
  else submenuSide.value = roomRight >= roomLeft ? 'right' : 'left'
}

function close(): void {
  open.value = false
  activeSection.value = null
}

function selectModel(option: CoreSelectOption): void {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  close()
}

function selectThinking(value: string): void {
  emit('update:thinkingMode', value)
  close()
}

function toggleShallow(): void {
  emit('update:shallowThinkingEnabled', !props.shallowThinkingEnabled)
  close()
}

function onPointerDown(event: PointerEvent): void {
  const target = event.target as Node | null
  if (!target || !root.value || root.value.contains(target)) return
  close()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && open.value) close()
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', updateSubmenuSide)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', updateSubmenuSide)
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
  max-width: min(230px, 42vw);
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

.core-model-thinking-menu__model,
.core-model-thinking-menu__thinking {
  overflow: hidden;
  text-overflow: ellipsis;
}

.core-model-thinking-menu__thinking {
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-weight: 600;
}

.core-model-thinking-menu__chevron {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 58%, transparent);
}

.core-model-thinking-menu__panel {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 8px);
  z-index: var(--z-popover, 60);
  width: max-content;
  max-width: calc(100vw - 24px);
  color: var(--text);
  animation: core-model-thinking-menu-in var(--dur-base) var(--ease-out);
  transform: translateX(-50%);
  transform-origin: bottom center;
}

.core-model-thinking-menu__card {
  min-width: 0;
  width: max-content;
  max-width: 240px;
  padding: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-radius: var(--radius);
  background: var(--theme-composer-background);
  box-shadow: var(--shadow-md);
}

.core-model-thinking-menu__card--submenu {
  position: absolute;
  bottom: 0;
}

.core-model-thinking-menu__card--submenu-right {
  left: calc(100% + var(--space-2));
  animation: core-model-thinking-submenu-right-in var(--dur-base) var(--ease-out);
}

.core-model-thinking-menu__card--submenu-left {
  right: calc(100% + var(--space-2));
  animation: core-model-thinking-submenu-left-in var(--dur-base) var(--ease-out);
}

.core-model-thinking-menu__card--submenu .core-model-thinking-menu__option > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-model-thinking-menu__model-list {
  max-height: calc(34px * 5);
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

.core-model-thinking-menu__provider {
  min-height: 34px;
  padding: var(--space-1) var(--space-2);
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  background: var(--theme-composer-background);
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .03em;
}

.core-model-thinking-menu__heading {
  padding: var(--space-1) var(--space-2);
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .03em;
}

.core-model-thinking-menu__option {
  width: 100%;
  min-height: 34px;
  padding: var(--space-1) var(--space-2);
  border: 0;
  border-radius: 0;
  position: relative;
  z-index: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.core-model-thinking-menu__option:hover,
.core-model-thinking-menu__option.active {
  background: transparent;
}

.core-model-thinking-menu__option::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  opacity: 0;
  pointer-events: none;
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  -webkit-mask-image: linear-gradient(to right, transparent, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), transparent);
  mask-image: linear-gradient(to right, transparent, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), transparent);
}

.core-model-thinking-menu__option:hover::before {
  opacity: 1;
}

.core-model-thinking-menu__option.active::before {
  opacity: 1;
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-model-thinking-menu__option > * {
  position: relative;
  z-index: 1;
}

.core-model-thinking-menu__parameter {
  grid-template-columns: auto minmax(0, max-content) auto;
  width: max-content;
  max-width: 224px;
  min-height: 40px;
  display: grid;
  align-items: center;
}

.core-model-thinking-menu__parameter[aria-expanded='true']::before {
  opacity: 1;
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-model-thinking-menu__parameter-label {
  font-size: 13px;
  font-weight: 750;
}

.core-model-thinking-menu__parameter-value {
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 12px;
  font-weight: 600;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-model-thinking-menu__parameter-chevron {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 58%, transparent);
}

.core-model-thinking-menu__option.active {
  color: var(--green);
}

.core-model-thinking-menu__option:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 24%, transparent);
  outline-offset: -2px;
}

.core-model-thinking-menu__option.disabled,
.core-model-thinking-menu__option:disabled {
  opacity: .42;
  cursor: default;
}

.core-model-thinking-menu__shallow {
  margin-top: var(--space-1);
  border-top: 1px solid color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-radius: 0;
}

.core-model-thinking-menu__check {
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 900;
}

.core-model-thinking-menu__empty {
  padding: var(--space-2);
  color: color-mix(in srgb, var(--text) 50%, transparent);
  font-size: 11px;
}

@keyframes core-model-thinking-menu-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes core-model-thinking-submenu-right-in {
  from { opacity: 0; transform: translateX(calc(var(--space-1) * -1)); }
  to { opacity: 1; transform: translateX(0); }
}

@keyframes core-model-thinking-submenu-left-in {
  from { opacity: 0; transform: translateX(var(--space-1)); }
  to { opacity: 1; transform: translateX(0); }
}

@media (max-width: 560px) {
  .core-model-thinking-menu__trigger { max-width: 42vw; }
}

@media (prefers-reduced-motion: reduce) {
  .core-model-thinking-menu__panel,
  .core-model-thinking-menu__card--submenu { animation: none; }
}
</style>
