<script setup lang="ts">
import '@/styles/sunday-motion.css'
import { t } from '@/i18n/index.ts'

import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

defineOptions({ name: 'UiSelect' })

type SelectOption = {
  value: string
  label: string
  selectedLabel?: string
  group?: string
  disabled?: boolean
  selected?: boolean
  separatorBefore?: boolean
  activeAccent?: boolean
}

const props = withDefaults(defineProps<{
  modelValue: string
  options: SelectOption[]
  placeholder?: string
  ariaLabel?: string
  /**
   * Direction the menu prefers: 'down' (default) or 'up'. The menu flips to the
   * other side whenever the preferred one cannot hold it.
   */
  direction?: 'up' | 'down'
  /**
   * Menu alignment: 'right' forces right-aligned; 'left' forces left-aligned;
   * omitted → auto: the menu flips to whichever side keeps it inside the
   * viewport, so it never widens the page.
   */
  menuAlign?: 'left' | 'right'
  /** Menu width floor in px; 0 makes the menu exactly as wide as the trigger. */
  menuMinWidth?: number
  /** Fixed menu width in px; wins over the trigger width and is clamped to the viewport. */
  menuWidth?: number
  menuMaxHeight?: number
  hideArrow?: boolean
  disabled?: boolean
}>(), {
  menuMinWidth: 280,
  menuMaxHeight: 320,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const triggerEl = ref<HTMLButtonElement | null>(null)
const menuEl = ref<HTMLElement | null>(null)

type MenuPlacement = {
  up: boolean
  alignRight: boolean
  left: number
  /** null when the menu hangs from its bottom edge (upward direction). */
  top: number | null
  bottom: number | null
  width: number
  maxHeight: number
}

const VIEWPORT_MARGIN = 8
const MENU_GAP = 6
const MENU_MIN_HEIGHT = 96

const placement = ref<MenuPlacement>({
  up: false,
  alignRight: false,
  left: 0,
  top: 0,
  bottom: null,
  width: 280,
  maxHeight: 320,
})
/** Height the placement is solved against; refreshed whenever the menu is measured. */
const naturalHeight = ref(0)
/**
 * False only for the frame the menu is measured in: the menu sits at its
 * preferred side and stays hidden, so even if that frame reached the screen the
 * user never sees it jump to the flipped side.
 */
const prepared = ref(false)
const menuVars = ref<Record<string, string>>({})

/**
 * The menu is teleported to body so no card can clip it, which drops the
 * scoped tokens the settings/plugins surfaces declare on their own root.
 * Copy the resolved values off the trigger at open time so the floating menu
 * keeps exactly the colours it had while rendered in place.
 */
// user:“确保视觉、功能和交互不退化”+(传送菜单时保留所在区域的配色与层级，避免被全屏编辑器遮住)
const MENU_SCOPED_VARS = ['--settings-control-solid', '--settings-control-text', '--ui-select-layer'] as const

function readScopedVars(): Record<string, string> {
  const element = triggerEl.value
  if (!element || typeof getComputedStyle !== 'function') return {}
  const computedStyle = getComputedStyle(element)
  const vars: Record<string, string> = {}
  for (const name of MENU_SCOPED_VARS) {
    const value = computedStyle.getPropertyValue(name).trim()
    if (value) vars[name] = value
  }
  return vars
}

function measureMenu(): number {
  const height = menuEl.value?.offsetHeight ?? 0
  return height > 0 ? height : props.menuMaxHeight
}

function resolvePlacement(height: number): MenuPlacement {
  const rect = triggerEl.value?.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const anchor = rect ?? { left: 0, right: 0, top: 0, bottom: 0, width: 0 }
  const viewportWidthLimit = Math.max(120, viewportWidth - VIEWPORT_MARGIN * 2)
  const width = Math.min(props.menuWidth ?? Math.max(props.menuMinWidth, anchor.width), viewportWidthLimit)
  const spaceBelow = viewportHeight - anchor.bottom - MENU_GAP - VIEWPORT_MARGIN
  const spaceAbove = anchor.top - MENU_GAP - VIEWPORT_MARGIN
  // 首选方向放不下、另一侧更宽裕时翻转：卡片底缘的触发器不再探出视口。
  let up = props.direction === 'up'
  const fits = up ? spaceAbove >= height : spaceBelow >= height
  if (!fits) {
    const roomAbove = spaceAbove > spaceBelow
    if (up ? !roomAbove : roomAbove) up = !up
  }
  const maxHeight = Math.max(MENU_MIN_HEIGHT, Math.min(props.menuMaxHeight, up ? spaceAbove : spaceBelow))
  const alignRight = props.menuAlign === 'right'
    || (!props.menuAlign && anchor.left + width > viewportWidth - VIEWPORT_MARGIN)
  const left = alignRight ? anchor.right - width : anchor.left
  return {
    up,
    alignRight,
    left: Math.min(Math.max(VIEWPORT_MARGIN, left), Math.max(VIEWPORT_MARGIN, viewportWidth - VIEWPORT_MARGIN - width)),
    top: up ? null : anchor.bottom + MENU_GAP,
    bottom: up ? viewportHeight - anchor.top + MENU_GAP : null,
    width,
    maxHeight,
  }
}

const menuStyle = computed<Record<string, string>>(() => {
  const current = placement.value
  return {
    left: `${current.left}px`,
    top: current.top === null ? 'auto' : `${current.top}px`,
    bottom: current.bottom === null ? 'auto' : `${current.bottom}px`,
    width: `${current.width}px`,
    maxHeight: `${current.maxHeight}px`,
    visibility: prepared.value ? 'visible' : 'hidden',
    ...menuVars.value,
  }
})

function onViewportChange(): void {
  if (!open.value) return
  placement.value = resolvePlacement(naturalHeight.value)
}

function startTrackingViewport(): void {
  window.addEventListener('resize', onViewportChange)
  // 滚动事件不冒泡：只有捕获阶段能听到整版页面、卡片这类内部滚动容器。
  document.addEventListener('scroll', onViewportChange, true)
}

function stopTrackingViewport(): void {
  window.removeEventListener('resize', onViewportChange)
  document.removeEventListener('scroll', onViewportChange, true)
}

async function openMenu(): Promise<void> {
  menuVars.value = readScopedVars()
  naturalHeight.value = props.menuMaxHeight
  prepared.value = false
  placement.value = resolvePlacement(props.menuMaxHeight)
  open.value = true
  startTrackingViewport()
  await nextTick()
  if (!open.value) return
  naturalHeight.value = measureMenu()
  placement.value = resolvePlacement(naturalHeight.value)
  prepared.value = true
  await nextTick()
  if (open.value) enabledOptions()[0]?.focus()
}

function closeMenu(): void {
  open.value = false
  prepared.value = false
  stopTrackingViewport()
}

// user:“确保视觉、功能和交互不退化”+(保存或加载导致控件禁用时立即关闭浮层，防止继续选择)。
watch(() => props.disabled, disabled => {
  if (disabled && open.value) closeMenu()
}, { flush: 'sync' })

watch(
  () => props.options,
  () => {
    if (!open.value) return
    // user:“确保视觉、功能和交互不退化”+(选项异步消失或禁用时保留键盘入口，不自动改变选中值)。
    const focused = document.activeElement instanceof HTMLButtonElement && menuEl.value?.contains(document.activeElement)
      ? document.activeElement : null
    void nextTick(() => {
      if (!open.value) return
      naturalHeight.value = measureMenu()
      placement.value = resolvePlacement(naturalHeight.value)
      if (focused && (!focused.isConnected || focused.disabled)
        && (document.activeElement === focused || document.activeElement === document.body)) {
        ;(enabledOptions()[0] || triggerEl.value)?.focus()
      }
    })
  },
  { deep: true },
)

const selectedLabel = computed(() => {
  const option = props.options.find((item) => item.value === props.modelValue)
  return option?.selectedLabel || option?.label?.replace(/^\s*-\s*/, '') || props.placeholder || t("未指定")
})

/** 触发器的状态类：强制侧与非强制侧（打开时按视口定）都如实反映。 */
const rootClasses = computed(() => ({
  open: open.value,
  'ui-select--up': placement.value.up,
  'ui-select--right': props.menuAlign === 'right' || (!props.menuAlign && placement.value.alignRight),
}))

const groupedOptions = computed(() => {
  const groups: Array<{ group: string; options: SelectOption[] }> = []
  const indexByGroup = new Map<string, number>()
  for (const option of props.options) {
    const group = option.group || ''
    let index = indexByGroup.get(group)
    if (index === undefined) {
      index = groups.length
      indexByGroup.set(group, index)
      groups.push({ group, options: [] })
    }
    groups[index].options.push(option)
  }
  return groups
})

function toggle() {
  if (props.disabled) return
  if (open.value) closeMenu()
  else void openMenu()
}

// user:“确保视觉、功能和交互不退化”+(共享下拉提供一致的键盘操作，禁用项不能获得焦点或被选择)
function enabledOptions(): HTMLButtonElement[] {
  return Array.from(menuEl.value?.querySelectorAll<HTMLButtonElement>('.ui-select-option:not(:disabled)') ?? [])
}

function onMenuKeydown(event: KeyboardEvent): void {
  // user:“确保视觉、功能和交互不退化”+(Tab 从触发器的位置继续前进，浮层关闭且不困住键盘焦点)
  if (event.key === 'Tab') {
    triggerEl.value?.focus()
    closeMenu()
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closeMenu()
    triggerEl.value?.focus()
    return
  }
  const options = enabledOptions()
  if (!options.length) return
  const current = options.indexOf(document.activeElement as HTMLButtonElement)
  let index: number
  if (event.key === 'ArrowDown') index = (current + 1) % options.length
  else if (event.key === 'ArrowUp') index = (current <= 0 ? options.length : current) - 1
  else if (event.key === 'Home') index = 0
  else if (event.key === 'End') index = options.length - 1
  else return
  event.preventDefault()
  options[index]?.focus()
}

function selectOption(option: SelectOption) {
  if (props.disabled || option.disabled) return
  emit('update:modelValue', option.value)
  closeMenu()
  triggerEl.value?.focus()
}

function onPointerDown(event: PointerEvent) {
  const target = event.target as Node | null
  if (!target) return
  if (root.value?.contains(target)) return
  // 菜单已传送到 body，不再包在 root 里，必须单独判定，否则点选项会先关掉菜单。
  if (menuEl.value?.contains(target)) return
  closeMenu()
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  stopTrackingViewport()
})
</script>

<template>
  <div ref="root" class="ui-select" :class="rootClasses">
    <button
      ref="triggerEl"
      class="ui-select-trigger"
      type="button"
      :disabled="disabled"
      :aria-label="ariaLabel || t('当前选择：{0}', { 0: selectedLabel })"
      :aria-expanded="open"
      @click="toggle"
      @keydown.esc="open && onMenuKeydown($event)"
      @keydown.tab="open && closeMenu()"
    >
      <span>{{ selectedLabel }}</span>
      <span v-if="!hideArrow" class="ui-select-arrow"></span>
    </button>
    <!-- 菜单传送到 body：卡片（整版界面滚动区、右栏玻璃面）都有 overflow，
         就地展开会被裁掉。坐标按触发器实算，仍贴着触发器出现。 -->
    <Teleport to="body">
      <!-- user:“做”+(真实下拉使用共有浮层开合，关闭时立即退出交互)。 -->
      <Transition name="sunday-motion-fade" @before-leave="el => el.setAttribute('inert', '')">
        <div
          v-if="open"
          ref="menuEl"
          class="ui-select-menu sunday-motion-popover"
          :class="{ 'ui-select-menu--up': placement.up }"
          :style="menuStyle"
          @keydown="onMenuKeydown"
        >
          <div v-for="group in groupedOptions" :key="group.group || 'default'" class="ui-select-group">
            <div v-if="group.group" class="ui-select-group-label">{{ group.group }}</div>
            <button
              v-for="option in group.options"
              :key="option.value"
              class="ui-select-option"
              :class="{
                active: option.selected ?? option.value === modelValue,
                'active-accent': option.activeAccent,
                'separator-before': option.separatorBefore,
                disabled: option.disabled,
              }"
              type="button"
              :disabled="option.disabled"
              @click="selectOption(option)"
            >
              {{ option.label }}
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped src="../styles/ui-select.css"></style>
