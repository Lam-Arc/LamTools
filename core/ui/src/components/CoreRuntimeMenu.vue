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
      <ShieldCheck class="core-runtime-menu__compact-icon" :size="16" :stroke-width="2" aria-hidden="true" />
    </button>

    <div v-if="open" class="core-runtime-menu__panel" role="menu">
      <section ref="parameterCard" class="core-runtime-menu__card core-runtime-menu__card--parameters" aria-label="运行模式与权限参数">
        <button
          class="core-runtime-menu__option core-runtime-menu__parameter"
          type="button"
          role="menuitem"
          aria-haspopup="menu"
          :aria-expanded="activeSection === 'mode'"
          data-runtime-section="mode"
          @mouseenter="activateSection('mode')"
          @focus="activateSection('mode')"
          @click="activateSection('mode')"
        >
          <span class="core-runtime-menu__parameter-label">运行模式</span>
          <span class="core-runtime-menu__parameter-value">{{ activeModeLabel }}</span>
          <ChevronRight class="core-runtime-menu__parameter-chevron" :size="15" :stroke-width="2" aria-hidden="true" />
        </button>
        <button
          class="core-runtime-menu__option core-runtime-menu__parameter"
          type="button"
          role="menuitem"
          aria-haspopup="menu"
          :aria-expanded="activeSection === 'permission'"
          data-runtime-section="permission"
          @mouseenter="activateSection('permission')"
          @focus="activateSection('permission')"
          @click="activateSection('permission')"
        >
          <span class="core-runtime-menu__parameter-label">权限审批</span>
          <span class="core-runtime-menu__parameter-value">{{ permissionLabel }}</span>
          <ChevronRight class="core-runtime-menu__parameter-chevron" :size="15" :stroke-width="2" aria-hidden="true" />
        </button>
      </section>

      <section
        v-if="activeSection === 'mode'"
        ref="submenuCard"
        class="core-runtime-menu__card core-runtime-menu__card--submenu"
        :class="'core-runtime-menu__card--submenu-' + submenuSide"
        role="menu"
        aria-label="运行模式选项"
        data-runtime-submenu="mode"
      >
        <div class="core-runtime-menu__heading">运行模式</div>
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

      <section
        v-else-if="activeSection === 'permission'"
        ref="submenuCard"
        class="core-runtime-menu__card core-runtime-menu__card--submenu"
        :class="'core-runtime-menu__card--submenu-' + submenuSide"
        role="menu"
        aria-label="权限审批选项"
        data-runtime-submenu="permission"
      >
        <div class="core-runtime-menu__heading">权限审批</div>
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
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ChevronDown, ChevronRight, ShieldCheck } from 'lucide-vue-next'
import {
  CORE_PERMISSION_PRESET_DESCRIPTIONS,
  CORE_PERMISSION_PRESET_LABELS,
  normalizeCorePermissionPreset,
  type CorePermissionPreset,
  type CoreSelectOption,
} from '../composer/execution'
import { useComposerMenuMotion } from '../motion/composerMenu'

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
const activeSection = ref<'mode' | 'permission' | null>(null)
const submenuSide = ref<'left' | 'right'>('right')
const root = ref<HTMLElement | null>(null)
const parameterCard = ref<HTMLElement | null>(null)
const submenuCard = ref<HTMLElement | null>(null)
const { animatePrimaryCard, animateSubmenuCard, cancel } = useComposerMenuMotion(root)

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
  if (props.disabled) return
  open.value = !open.value
  activeSection.value = null
  if (!open.value) {
    cancel()
    return
  }
  void nextTick(() => animatePrimaryCard(parameterCard.value, ':scope > .core-runtime-menu__option'))
}

function activateSection(section: 'mode' | 'permission'): void {
  if (activeSection.value === section) return
  activeSection.value = section
  void nextTick(() => {
    updateSubmenuSide()
    animateSubmenuCard(
      submenuCard.value,
      submenuSide.value,
      ':scope > .core-runtime-menu__heading, :scope > .core-runtime-menu__option, :scope > .core-runtime-menu__empty, :scope > .core-runtime-menu__warning',
    )
  })
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
  cancel()
  open.value = false
  activeSection.value = null
}

function selectMode(option: CoreSelectOption): void {
  if (option.disabled) return
  emit('update:activeMode', option.value)
  close()
}

function selectPermission(value: string): void {
  emit('update:permissionPreset', normalizeCorePermissionPreset(value))
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

.core-runtime-menu__compact-icon {
  display: none;
}

.core-runtime-menu__panel {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 8px);
  z-index: var(--z-popover, 60);
  width: max-content;
  max-width: calc(100vw - 24px);
  color: var(--text);
  transform: translateX(-50%);
  transform-origin: bottom center;
}

.core-runtime-menu__card {
  min-width: 0;
  width: max-content;
  max-width: 240px;
  padding: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-radius: var(--radius);
  background: var(--theme-composer-background);
  box-shadow: var(--shadow-md);
}

.core-runtime-menu__card--submenu {
  position: absolute;
  bottom: 0;
}

.core-runtime-menu__card--submenu-right {
  left: calc(100% + var(--space-2));
}

.core-runtime-menu__card--submenu-left {
  right: calc(100% + var(--space-2));
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
  opacity: 0;
}

.core-runtime-menu__option.active:hover::before {
  opacity: 1;
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.core-runtime-menu__option:disabled::before {
  opacity: 0;
}

.core-runtime-menu__option > * {
  position: relative;
  z-index: 1;
}

.core-runtime-menu__card--submenu .core-runtime-menu__option > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-runtime-menu__parameter {
  grid-template-columns: minmax(0, 1fr) minmax(0, max-content) auto;
  width: 100%;
  max-width: 224px;
  min-height: 40px;
  display: grid;
  align-items: center;
}

.core-runtime-menu__parameter-label {
  font-size: 13px;
  font-weight: 750;
}

.core-runtime-menu__parameter-value {
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 12px;
  font-weight: 600;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-runtime-menu__parameter-chevron {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 58%, transparent);
}

.core-runtime-menu__option.active {
  color: var(--green);
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

@container composer (max-width: 480px) {
  .core-runtime-menu__trigger {
    width: 28px;
    padding: 0;
    justify-content: center;
  }

  .core-runtime-menu__mode,
  .core-runtime-menu__permission,
  .core-runtime-menu__separator,
  .core-runtime-menu__chevron {
    display: none;
  }

  .core-runtime-menu__compact-icon {
    display: block;
  }
}

</style>
