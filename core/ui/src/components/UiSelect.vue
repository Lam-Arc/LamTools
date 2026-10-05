<script setup lang="ts">
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
const MENU_SCOPED_VARS = ['--settings-control-solid', '--settings-control-text'] as const

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
  naturalHeight.value = measureMenu()
  placement.value = resolvePlacement(naturalHeight.value)
  prepared.value = true
}

function closeMenu(): void {
  open.value = false
  prepared.value = false
  stopTrackingViewport()
}

watch(
  () => props.options,
  () => {
    if (!open.value) return
    void nextTick(() => {
      naturalHeight.value = measureMenu()
      placement.value = resolvePlacement(naturalHeight.value)
    })
  },
)

const selectedLabel = computed(() => {
  const option = props.options.find((item) => item.value === props.modelValue)
  return option?.selectedLabel || option?.label?.replace(/^\s*-\s*/, '') || props.placeholder || '未指定'
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

function selectOption(option: SelectOption) {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  closeMenu()
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
      :aria-label="ariaLabel || `当前选择：${selectedLabel}`"
      :aria-expanded="open"
      @click="toggle"
    >
      <span>{{ selectedLabel }}</span>
      <span v-if="!hideArrow" class="ui-select-arrow"></span>
    </button>
    <!-- 菜单传送到 body：卡片（整版界面滚动区、右栏玻璃面）都有 overflow，
         就地展开会被裁掉。坐标按触发器实算，仍贴着触发器出现。 -->
    <Teleport to="body">
      <div
        v-if="open"
        ref="menuEl"
        class="ui-select-menu"
        :class="{ 'ui-select-menu--up': placement.up }"
        :style="menuStyle"
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
            @click="selectOption(option)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.ui-select {
  /* 箭头槽位：触发器右侧必须按「内缩 + 箭头宽 + 间隙」预留，
     否则短标签（尤其 CJK，如「自动」）会被箭头压住。 */
  --ui-select-arrow-inset: 11px;
  --ui-select-arrow-size: 7px;
  --ui-select-arrow-gap: var(--space-1);
  position: relative;
  min-width: 0;
}

.ui-select-trigger {
  width: 100%;
  min-height: 32px;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #f4f1ec)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, var(--theme-control-solid, #242424)) 70%, transparent);
  color: var(--settings-control-text, var(--theme-control-text, #f4f1ec));
  padding: 0 calc(var(--ui-select-arrow-inset) + var(--ui-select-arrow-size) + var(--ui-select-arrow-gap)) 0 var(--space-2);
  display: inline-flex;
  align-items: center;
  text-align: left;
  font-size: 13px;
}

.ui-select-trigger:disabled {
  opacity: 0.45;
  cursor: default;
}

.ui-select-trigger span:first-child {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ui-select-arrow {
  position: absolute;
  right: var(--ui-select-arrow-inset);
  top: 50%;
  width: var(--ui-select-arrow-size);
  height: var(--ui-select-arrow-size);
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  opacity: .7;
  transform: translateY(-65%) rotate(45deg);
  transition: transform var(--dur-fast) var(--ease-out);
}

.ui-select.open .ui-select-arrow {
  transform: translateY(-35%) rotate(225deg);
}

.ui-select-menu {
  /* 传送到 body 的浮层：fixed 定位，坐标/宽高由脚本按视口算好，
     任何 overflow 祖先都裁不到它。 */
  position: fixed;
  left: 0;
  top: 0;
  z-index: var(--z-popover, 60);
  max-height: 320px;
  overflow: auto;
  border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
  border-radius: var(--radius);
  /* 菜单是 control area；settings 预览优先使用作用域内实色 token，
     其他上下文回退到 control 主题，不跨用 main/composer 文字色。 */
  background: var(--settings-control-solid, var(--theme-control-background, #242424));
  color: var(--settings-control-text, var(--theme-control-text, #f4f1ec));
  box-shadow: var(--shadow-md);
  padding: 6px;
  display: grid;
  gap: 4px;
  /* 弹出入场：scale+淡入（popover-in 与项目菜单同源） */
  animation: popover-in var(--dur-base) var(--ease-out);
  transform-origin: top;
}
.ui-select-menu--up {
  transform-origin: bottom;
}

.ui-select-group {
  display: grid;
  gap: 2px;
}

.ui-select-group + .ui-select-group {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent);
}

.ui-select-group-label {
  padding: 4px 9px 3px;
  color: color-mix(in srgb, currentColor 72%, transparent);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ui-select-option {
  min-height: 30px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  padding: 5px 9px;
  display: block;
  text-align: left;
  font-size: 13px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  position: relative;
}
.ui-select-option::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}
.ui-select-option:hover::before {
  background: color-mix(in srgb, currentColor var(--alpha-hover), transparent);
}
.ui-select-option.active::before {
  background: color-mix(in srgb, currentColor var(--alpha-active), transparent);
}

.ui-select-option.active.active-accent {
  background: transparent;
  color: var(--green, #32d17d);
}

.ui-select-option.separator-before {
  position: relative;
  margin-top: 7px;
}

.ui-select-option.separator-before::after {
  content: '';
  position: absolute;
  left: 9px;
  right: 9px;
  top: -4px;
  height: 1px;
  background: color-mix(in srgb, currentColor 16%, transparent);
}

.ui-select-option.disabled {
  opacity: .45;
  cursor: default;
}

@media (prefers-reduced-motion: reduce) {
  .ui-select-arrow {
    transition: none;
  }

  .ui-select-menu {
    animation: none;
  }
}
</style>
