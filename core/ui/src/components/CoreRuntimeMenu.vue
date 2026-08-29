<template>
  <div ref="root" class="core-runtime-menu" data-core-runtime-menu>
    <button
      class="core-runtime-menu__trigger"
      type="button"
      :disabled="disabled"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      @click="toggle"
    >
      <span class="core-runtime-menu__mode">{{ activeModeLabel }}</span>
      <span class="core-runtime-menu__separator" aria-hidden="true">·</span>
      <span class="core-runtime-menu__permission">{{ permissionLabel }}</span>
      <ChevronDown class="core-runtime-menu__chevron" :size="14" :stroke-width="2" aria-hidden="true" />
    </button>

    <div v-if="open" class="core-runtime-menu__panel" role="menu">
      <section class="core-runtime-menu__card" aria-labelledby="runtime-mode-heading">
        <div id="runtime-mode-heading" class="core-runtime-menu__heading">运行模式</div>
        <button
          v-for="option in modeOptions"
          :key="option.value"
          class="core-runtime-menu__option"
          :class="{ active: option.value === activeMode, disabled: option.disabled }"
          type="button"
          role="menuitemradio"
          :aria-checked="option.value === activeMode"
          :disabled="option.disabled"
          :data-runtime-mode-option="option.value"
          @click="selectMode(option)"
        >
          <span>{{ option.label }}</span>
          <span v-if="option.value === activeMode" class="core-runtime-menu__check" aria-hidden="true">✓</span>
        </button>
        <div v-if="modeOptions.length === 0" class="core-runtime-menu__empty">当前模式由插件提供</div>
      </section>

      <section class="core-runtime-menu__card" aria-labelledby="runtime-permission-heading">
        <div id="runtime-permission-heading" class="core-runtime-menu__heading">权限审批</div>
        <button
          v-for="option in permissionOptions"
          :key="option.value"
          class="core-runtime-menu__option"
          :class="{ active: option.value === permissionPreset }"
          type="button"
          role="menuitemradio"
          :aria-checked="option.value === permissionPreset"
          :data-runtime-permission-option="option.value"
          @click="selectPermission(option.value)"
        >
          <span class="core-runtime-menu__option-copy">
            <span>{{ option.label }}</span>
            <small>{{ option.description }}</small>
          </span>
          <span v-if="option.value === permissionPreset" class="core-runtime-menu__check" aria-hidden="true">✓</span>
        </button>
        <p v-if="permissionPreset === 'full_access'" class="core-runtime-menu__warning">
          完全编辑、自动批准，并允许访问工作目录外
        </p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import {
  CORE_PERMISSION_PRESET_DESCRIPTIONS,
  CORE_PERMISSION_PRESET_LABELS,
  normalizeCorePermissionPreset,
  type CorePermissionPreset,
  type CoreSelectOption,
} from '../composer/execution'

const props = withDefaults(defineProps<{
  activeMode: string
  activeModeLabel?: string
  modeOptions?: CoreSelectOption[]
  permissionPreset: CorePermissionPreset | string
  disabled?: boolean
}>(), {
  modeOptions: () => [],
  disabled: false,
})

const emit = defineEmits<{
  'update:activeMode': [value: string]
  'update:permissionPreset': [value: CorePermissionPreset]
}>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const permissionOptions = computed(() => (
  (['ask', 'auto', 'full_access'] as CorePermissionPreset[]).map((value) => ({
    value,
    label: CORE_PERMISSION_PRESET_LABELS[value],
    description: CORE_PERMISSION_PRESET_DESCRIPTIONS[value],
  }))
))

const activeModeLabel = computed(() => (
  props.activeModeLabel
    || props.modeOptions.find((option) => option.value === props.activeMode)?.selectedLabel
    || props.modeOptions.find((option) => option.value === props.activeMode)?.label
    || props.activeMode
    || '模式'
))

const permissionLabel = computed(() => (
  CORE_PERMISSION_PRESET_LABELS[normalizeCorePermissionPreset(props.permissionPreset)]
))

const ariaLabel = computed(() => `运行模式与权限：${activeModeLabel.value} · ${permissionLabel.value}`)

function toggle(): void {
  if (!props.disabled) open.value = !open.value
}

function selectMode(option: CoreSelectOption): void {
  if (option.disabled) return
  emit('update:activeMode', option.value)
  open.value = false
}

function selectPermission(value: string): void {
  emit('update:permissionPreset', normalizeCorePermissionPreset(value))
  open.value = false
}

function onPointerDown(event: PointerEvent): void {
  const target = event.target as Node | null
  if (!target || !root.value || root.value.contains(target)) return
  open.value = false
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && open.value) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.core-runtime-menu {
  position: relative;
  flex: 0 0 auto;
  --text: var(--theme-composer-text);
}

.core-runtime-menu__trigger {
  min-width: 0;
  max-width: min(190px, 34vw);
  height: 28px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  background: transparent;
  color: color-mix(in srgb, var(--text) 86%, transparent);
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.core-runtime-menu__trigger:hover,
.core-runtime-menu__trigger[aria-expanded='true'] {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.core-runtime-menu__trigger[aria-expanded='true'] {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-runtime-menu__trigger:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 28%, transparent);
  outline-offset: 2px;
}

.core-runtime-menu__mode,
.core-runtime-menu__permission {
  overflow: hidden;
  text-overflow: ellipsis;
}

.core-runtime-menu__permission {
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-weight: 600;
}

.core-runtime-menu__separator {
  color: color-mix(in srgb, var(--text) 38%, transparent);
}

.core-runtime-menu__chevron {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 58%, transparent);
}

.core-runtime-menu__panel {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  z-index: var(--z-popover, 60);
  width: min(330px, calc(100vw - 24px));
  padding: var(--space-2);
  display: grid;
  gap: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-radius: var(--radius);
  background: var(--theme-composer-background);
  color: var(--text);
  box-shadow: var(--shadow-md);
  animation: core-runtime-menu-in var(--dur-base) var(--ease-out);
  transform-origin: bottom left;
}

.core-runtime-menu__card {
  min-width: 0;
  padding: var(--space-1);
  border: 1px solid color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  border-radius: var(--radius-sm);
  background: var(--theme-composer-soft-background);
}

.core-runtime-menu__heading {
  padding: var(--space-1) var(--space-2);
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .03em;
}

.core-runtime-menu__option {
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

.core-runtime-menu__option:hover,
.core-runtime-menu__option.active {
  background: transparent;
}

.core-runtime-menu__option::before {
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

.core-runtime-menu__option:hover::before {
  opacity: 1;
}

.core-runtime-menu__option.active::before {
  opacity: 1;
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-runtime-menu__option:disabled::before {
  opacity: 0;
}

.core-runtime-menu__option > * {
  position: relative;
  z-index: 1;
}

.core-runtime-menu__option.active {
  color: var(--green, #32d17d);
}

.core-runtime-menu__option:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 24%, transparent);
  outline-offset: -2px;
}

.core-runtime-menu__option.disabled,
.core-runtime-menu__option:disabled {
  opacity: .42;
  cursor: default;
}

.core-runtime-menu__option-copy {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.core-runtime-menu__option-copy small {
  color: color-mix(in srgb, var(--text) 53%, transparent);
  font-size: 10px;
  font-weight: 500;
}

.core-runtime-menu__check {
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 900;
}

.core-runtime-menu__empty {
  padding: var(--space-2);
  color: color-mix(in srgb, var(--text) 50%, transparent);
  font-size: 11px;
}

.core-runtime-menu__warning {
  margin: var(--space-1) var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid color-mix(in srgb, var(--orange) 28%, transparent);
  color: var(--orange);
  font-size: 10px;
  line-height: 1.4;
}

@keyframes core-runtime-menu-in {
  from { opacity: 0; transform: translateY(var(--space-1)) scale(.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@media (max-width: 560px) {
  .core-runtime-menu__trigger { max-width: 42vw; }
  .core-runtime-menu__panel { left: -4px; }
}

@media (prefers-reduced-motion: reduce) {
  .core-runtime-menu__panel { animation: none; }
}
</style>
