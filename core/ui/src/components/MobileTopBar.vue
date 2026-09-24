<template>
  <nav v-show="available && !hidden" ref="root" class="mobile-top-bar" aria-label="移动端快捷操作">
    <button
      class="mobile-top-bar__button mobile-top-bar__sidebar-button"
      type="button"
      aria-label="打开左侧会话栏"
      title="会话与项目"
      data-mobile-sidebar-button
      @click="emit('open-sidebar')"
    >
      <PanelLeft :size="18" :stroke-width="1.8" aria-hidden="true" />
    </button>

    <div
      v-show="syncing"
      class="mobile-top-bar__sync optical-glass"
      role="status"
      aria-live="polite"
    >
      <span ref="syncIcon" class="mobile-top-bar__sync-icon" aria-hidden="true">
        <RefreshCw :size="14" :stroke-width="1.9" />
      </span>
      <span>正在同步</span>
    </div>

    <div
      ref="dock"
      class="mobile-command-dock"
      :style="{
        '--mobile-command-panel-x': `${panelOffsetX}px`,
        '--mobile-command-panel-y': `${panelOffsetY}px`,
      }"
      :class="{
        'mobile-command-dock--open-left': panelOpensLeft,
        'mobile-command-dock--open-up': panelOpensUp,
      }"
    >
      <button
        ref="dockTrigger"
        class="mobile-top-bar__button mobile-command-dock__trigger"
        type="button"
        :aria-expanded="panelOpen"
        aria-controls="mobile-command-panel"
        :aria-label="`打开快捷操作，当前模式 ${activeModeLabel}`"
        title="快捷操作"
        data-mobile-command-button
        @click="togglePanel"
      >
        <Blocks :size="18" :stroke-width="1.9" aria-hidden="true" />
      </button>

      <section
        id="mobile-command-panel"
        ref="panel"
        v-show="panelOpen"
        class="mobile-command-dock__panel optical-glass"
        aria-label="快捷操作"
        data-mobile-command-panel
      >
        <div class="mobile-command-dock__heading">
          <span>切换模式</span>
        </div>
        <div class="mobile-command-dock__modes" role="listbox" aria-label="可用模式">
          <button
            v-for="option in modeOptions"
            :key="option.id"
            class="mobile-command-dock__mode"
            :class="{ 'is-active': option.id === activeModeId }"
            type="button"
            role="option"
            :aria-selected="option.id === activeModeId"
            :data-mobile-mode-option="option.id"
            @click="selectMode(option.id)"
          >
            <span>{{ option.label }}</span>
            <Check v-if="option.id === activeModeId" :size="14" :stroke-width="2" aria-hidden="true" />
          </button>
        </div>

        <div class="mobile-command-dock__divider" aria-hidden="true"></div>
        <div class="mobile-command-dock__actions">
          <button type="button" data-mobile-search-button @click="runAction('open-search')">
            <Search :size="16" :stroke-width="1.8" aria-hidden="true" />
            <span>搜索</span>
          </button>
          <button type="button" data-mobile-settings-button @click="runAction('open-settings')">
            <Settings :size="16" :stroke-width="1.8" aria-hidden="true" />
            <span>设置</span>
          </button>
          <button type="button" data-mobile-plugins-button @click="runAction('open-plugins')">
            <Puzzle :size="16" :stroke-width="1.8" aria-hidden="true" />
            <span>插件</span>
          </button>
          <button type="button" data-mobile-arrange-button @click="runAction('open-arrange')">
            <CalendarClock :size="16" :stroke-width="1.8" aria-hidden="true" />
            <span>长期安排</span>
          </button>
          <button type="button" data-mobile-account-button @click="runAction('open-account')">
            <UserRound :size="16" :stroke-width="1.8" aria-hidden="true" />
            <span>{{ accountLabel }}</span>
          </button>
        </div>
      </section>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Blocks, CalendarClock, Check, PanelLeft, Puzzle, RefreshCw, Search, Settings, UserRound } from 'lucide-vue-next'
import { gsap } from 'gsap'

export interface MobileModeOption {
  id: string
  label: string
}

const props = withDefaults(defineProps<{
  available?: boolean
  hidden?: boolean
  syncing?: boolean
  modeOptions?: MobileModeOption[]
  activeModeId?: string
  accountLabel?: string
}>(), {
  available: true,
  hidden: false,
  syncing: false,
  modeOptions: () => [],
  activeModeId: '',
  accountLabel: '登录 / 账号',
})

const emit = defineEmits<{
  'open-sidebar': []
  'open-account': []
  'open-search': []
  'open-settings': []
  'open-plugins': []
  'open-arrange': []
  'select-mode': [id: string]
}>()

const root = ref<HTMLElement | null>(null)
const dock = ref<HTMLElement | null>(null)
const dockTrigger = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const syncIcon = ref<HTMLElement | null>(null)
const panelOpen = ref(false)
const panelOpensLeft = ref(true)
const panelOpensUp = ref(false)
const panelOffsetX = ref(0)
const panelOffsetY = ref(52)
let motion: ReturnType<typeof gsap.matchMedia> | null = null
let syncTween: gsap.core.Tween | null = null
let panelTween: gsap.core.Tween | null = null
let motionAllowed = false
const activeModeLabel = computed(() => (
  props.modeOptions.find((option) => option.id === props.activeModeId)?.label || '默认'
))

function updatePanelDirection(): void {
  const trigger = dockTrigger.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const viewportGap = 12
  const panelWidth = Math.min(panel.value?.offsetWidth || 286, Math.max(0, window.innerWidth - viewportGap * 2))
  const panelHeight = Math.min(panel.value?.offsetHeight || 340, Math.max(0, window.innerHeight - viewportGap * 2))
  const preferredLeft = rect.right - panelWidth
  const panelLeft = Math.min(
    Math.max(preferredLeft, viewportGap),
    Math.max(viewportGap, window.innerWidth - panelWidth - viewportGap),
  )
  let preferredTop = rect.bottom + 8
  if (preferredTop + panelHeight > window.innerHeight - viewportGap) {
    preferredTop = rect.top - panelHeight - 8
  }
  const panelTop = Math.min(
    Math.max(preferredTop, viewportGap),
    Math.max(viewportGap, window.innerHeight - panelHeight - viewportGap),
  )
  panelOffsetX.value = panelLeft - rect.left
  panelOffsetY.value = panelTop - rect.top
  panelOpensLeft.value = panelLeft < rect.left
  panelOpensUp.value = panelTop < rect.top
}

function togglePanel(): void {
  panelOpen.value = !panelOpen.value
}

function closePanel(): void {
  panelOpen.value = false
}

function selectMode(id: string): void {
  emit('select-mode', id)
  closePanel()
}

function runAction(event: 'open-search' | 'open-settings' | 'open-account' | 'open-plugins' | 'open-arrange'): void {
  if (event === 'open-search') emit('open-search')
  else if (event === 'open-settings') emit('open-settings')
  else if (event === 'open-account') emit('open-account')
  else if (event === 'open-plugins') emit('open-plugins')
  else emit('open-arrange')
  closePanel()
}

function handleDocumentPointerDown(event: PointerEvent): void {
  const target = event.target
  if (target instanceof Node && !dock.value?.contains(target)) closePanel()
}

function handleDocumentKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closePanel()
}

function handleViewportResize(): void {
  updatePanelDirection()
}

watch(() => [props.hidden, props.available] as const, ([hidden, available]) => {
  if (hidden || !available) closePanel()
})

watch(panelOpen, async (open) => {
  panelTween?.kill()
  panelTween = null
  if (!open) return
  await nextTick()
  updatePanelDirection()
  if (!motionAllowed || !panel.value) return
  panelTween = gsap.fromTo(panel.value,
    { autoAlpha: 0, y: panelOpensUp.value ? 6 : -6, scale: 0.98 },
    { autoAlpha: 1, y: 0, scale: 1, duration: 0.18, ease: 'power2.out', clearProps: 'opacity,visibility,transform' },
  )
})

onMounted(() => {
  motion = gsap.matchMedia()
  motion.add('(prefers-reduced-motion: no-preference)', () => {
    motionAllowed = true
    const stop = watch(
      () => [props.syncing, props.hidden, props.available] as const,
      ([syncing, hidden, available]) => {
        syncTween?.kill()
        syncTween = null
        const icon = syncIcon.value
        if (!icon) return
        if (!syncing || hidden || !available) {
          gsap.set(icon, { rotation: 0 })
          return
        }
        syncTween = gsap.to(icon, {
          rotation: 360,
          duration: 1.1,
          ease: 'none',
          repeat: -1,
          transformOrigin: '50% 50%',
        })
      },
      { immediate: true },
    )
    return () => {
      motionAllowed = false
      stop()
      syncTween?.kill()
      syncTween = null
    }
  }, root.value || undefined)

  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeydown)
  window.addEventListener('resize', handleViewportResize)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeydown)
  window.removeEventListener('resize', handleViewportResize)
  panelTween?.kill()
  panelTween = null
  syncTween?.kill()
  syncTween = null
  motion?.revert()
  motion = null
})
</script>

<style scoped>
.mobile-top-bar {
  --text: var(--theme-main-text);
  position: fixed;
  inset: 0;
  z-index: var(--z-popover);
  pointer-events: none;
}

.mobile-top-bar__button {
  position: fixed;
  top: max(var(--space-2), var(--mobile-header-offset, env(safe-area-inset-top, 0px)));
  left: var(--space-3);
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border-radius: var(--radius-sm);
  color: var(--text);
  cursor: pointer;
  pointer-events: auto;
  touch-action: none;
  transition: filter var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
  -webkit-tap-highlight-color: transparent;
}

.mobile-top-bar__button:hover {
  filter: brightness(1.015);
}

.mobile-top-bar__button:active {
  transform: scale(.98);
}

.mobile-top-bar__sidebar-button {
  border: 0;
  background: transparent;
  box-shadow: none;
}

.mobile-top-bar__button:focus-visible,
.mobile-command-dock__panel button:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 72%, transparent);
  outline-offset: var(--space-1);
}

.mobile-top-bar__sync {
  position: fixed;
  top: max(var(--space-3), var(--mobile-header-offset, env(safe-area-inset-top, 0px)));
  left: 50%;
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: color-mix(in srgb, var(--text) 72%, transparent);
  font-size: 12px;
  font-weight: 650;
  pointer-events: none;
  transform: translateX(-50%);
}

.mobile-top-bar__sync-icon {
  display: grid;
  place-items: center;
}

.mobile-command-dock {
  position: fixed;
  top: max(var(--space-2), var(--mobile-header-offset, env(safe-area-inset-top, 0px)));
  right: var(--space-3);
  width: 44px;
  height: 44px;
  pointer-events: none;
}

.mobile-command-dock__trigger {
  position: relative;
  inset: auto;
  border: 0;
  background: transparent;
  box-shadow: none;
  touch-action: manipulation;
}

.mobile-command-dock__panel {
  position: absolute;
  top: var(--mobile-command-panel-y);
  left: var(--mobile-command-panel-x);
  width: min(286px, calc(100vw - var(--space-6)));
  box-sizing: border-box;
  padding: var(--space-3);
  border-radius: var(--radius-lg);
  color: var(--text);
  pointer-events: auto;
  transform-origin: top right;
}

.mobile-command-dock:not(.mobile-command-dock--open-left) .mobile-command-dock__panel {
  transform-origin: top left;
}

.mobile-command-dock--open-up .mobile-command-dock__panel {
  transform-origin: bottom right;
}

.mobile-command-dock--open-up:not(.mobile-command-dock--open-left) .mobile-command-dock__panel {
  transform-origin: bottom left;
}

.mobile-command-dock__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: 24px;
  padding: 0 var(--space-2);
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}

.mobile-command-dock__modes,
.mobile-command-dock__actions {
  display: grid;
  gap: var(--space-1);
}

.mobile-command-dock__mode,
.mobile-command-dock__actions button {
  display: flex;
  width: 100%;
  min-height: 40px;
  align-items: center;
  gap: var(--space-2);
  justify-content: flex-start;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 78%, transparent);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-command-dock__mode {
  justify-content: space-between;
}

.mobile-command-dock__mode:hover,
.mobile-command-dock__actions button:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.mobile-command-dock__mode:active,
.mobile-command-dock__actions button:active,
.mobile-command-dock__mode.is-active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  color: var(--text);
}

.mobile-command-dock__divider {
  height: 1px;
  margin: var(--space-2);
  background: color-mix(in srgb, var(--text) 10%, transparent);
}

@media (prefers-reduced-motion: reduce) {
  .mobile-top-bar__button {
    transition: none;
    transform: none !important;
  }

  .mobile-command-dock__mode,
  .mobile-command-dock__actions button {
    transition: none;
    transform: none !important;
  }

  .mobile-top-bar__sync-icon,
  .mobile-command-dock__panel {
    transform: none !important;
  }
}
</style>
