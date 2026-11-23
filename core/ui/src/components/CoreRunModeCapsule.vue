<template>
  <!-- user:“输入框上方是一个三选一的胶囊，发送第一条消息时，定下该会话模式”“仅聊天和工作模式”+
       (只渲染 CORE_RUN_MODES 里的聊天与工作；旧存档里的 auto 读进来已归一成工作)。
       user:“这个空间怎么看也不像会互相挤”“为什么有那个小竖杠”+
       (空间够就按原样显示等宽两格；只有放不下时才收紧、再收成单个按钮。选中态只用底色块，不画竖条)。 -->
  <div
    ref="root"
    class="core-run-mode"
    :class="[`core-run-mode--${tier}`, { 'core-run-mode--locked': !selectable }]"
    data-run-mode-capsule
    :data-run-mode-tier="tier"
  >
    <!-- 一档/二档（以及锁定态）：两格并排。互斥两选一用 radiogroup 语义，Tab 进、Enter/空格切。 -->
    <div
      v-if="tier !== 'icon' || !selectable"
      class="core-run-mode__bar"
      role="radiogroup"
      :aria-label="t('会话运行模式')"
    >
      <template v-if="selectable">
        <button
          v-for="option in options"
          :key="option.value"
          type="button"
          role="radio"
          class="core-run-mode__pill"
          :class="{ 'is-active': option.value === activeMode }"
          :aria-checked="option.value === activeMode"
          :title="option.description"
          :data-run-mode-option="option.value"
          @click="$emit('update:modelValue', option.value)"
        >
          <span class="core-run-mode__label">{{ option.label }}</span>
        </button>
      </template>
      <span v-else class="core-run-mode__pill is-active" :title="activeDescription" data-run-mode-locked>
        <span class="core-run-mode__label">{{ activeLabel }}</span>
      </span>
    </div>

    <!-- 三档：图标 + 当前项，点开才是菜单；不换行、不撑破布局。 -->
    <div v-else class="core-run-mode__compact">
      <button
        type="button"
        class="core-run-mode__trigger"
        :class="{ 'is-open': menuOpen }"
        :aria-label="t('切换运行模式')"
        aria-haspopup="listbox"
        :aria-expanded="menuOpen"
        :title="activeDescription"
        data-run-mode-trigger
        @click="menuOpen = !menuOpen"
        @keydown.esc.prevent="menuOpen = false"
      >
        <component :is="activeIcon" :size="14" aria-hidden="true" />
        <span class="core-run-mode__label core-run-mode__current">{{ activeLabel }}</span>
      </button>
      <ul
        v-if="menuOpen"
        class="core-run-mode__menu"
        role="listbox"
        :aria-label="t('会话运行模式')"
        data-run-mode-menu
        @keydown.esc.prevent="menuOpen = false"
      >
        <li v-for="option in options" :key="option.value" role="option" :aria-selected="option.value === activeMode">
          <button
            type="button"
            class="core-run-mode__menu-item"
            :class="{ 'is-active': option.value === activeMode }"
            :data-run-mode-option="option.value"
            :title="option.description"
            @click="pick(option.value)"
          >
            <component :is="iconFor(option.value)" :size="14" aria-hidden="true" />
            <span class="core-run-mode__label">{{ option.label }}</span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, type Component } from 'vue'
import { MessageCircle, Wrench } from 'lucide-vue-next'

import { t } from '@/i18n/index.ts'
import { runModeTier, type RunModeTier } from '@/composer/runModeTier.ts'
import {
  CORE_RUN_MODE_DESCRIPTIONS,
  CORE_RUN_MODE_LABELS,
  CORE_RUN_MODES,
  normalizeCoreRunMode,
  type CoreRunMode,
} from '@/composer/runMode.ts'

const props = withDefaults(defineProps<{
  modelValue?: string
  /** 只有还没发过消息的会话能改模式。 */
  selectable?: boolean
  /**
   * 覆盖“容器宽度”（输入栏这一行的宽度）。生产不传：组件自己量根节点的父元素。
   * user:“容器宽度 320/420/560 三档下的类名/布局断言”+(jsdom 不做布局，
   * 与其去桩父元素的 clientWidth，不如给组件一个显式入口：测试传值、生产测量)。
   */
  containerWidth?: number
}>(), {
  modelValue: 'work',
  selectable: true,
})

const options = computed(() => CORE_RUN_MODES.map((value) => ({
  value,
  label: t(CORE_RUN_MODE_LABELS[value]),
  description: t(CORE_RUN_MODE_DESCRIPTIONS[value]),
})))

const activeMode = computed(() => normalizeCoreRunMode(props.modelValue))
const activeLabel = computed(() => t(CORE_RUN_MODE_LABELS[activeMode.value]))
const activeDescription = computed(() => t(CORE_RUN_MODE_DESCRIPTIONS[activeMode.value]))

const ICONS: Record<string, Component> = { chat: MessageCircle, work: Wrench }
function iconFor(mode: CoreRunMode): Component { return ICONS[mode] ?? MessageCircle }
const activeIcon = computed(() => iconFor(activeMode.value))

// user:“这个空间怎么看也不像会互相挤，肯定是哪里有问题”+
// (胶囊渲染在空会话引导块 `.empty-session-hero` 里，不在输入栏那一行：那里没有“和输入框抢宽度”。
//  档位仍按“装它的那块有多宽”来定，但先找真正的宿主，找不到才退回 composer 容器)。
const root = ref<HTMLElement | null>(null)
const tier = ref<RunModeTier>(runModeTier(props.containerWidth ?? 0))
const menuOpen = ref(false)

const CONTAINER_SELECTOR = '.empty-session-hero, .composer-bottom, .composer-main-card, .composer-bar'

function composerContainer(): HTMLElement | null {
  return root.value?.closest<HTMLElement>(CONTAINER_SELECTOR) ?? null
}

function containerWidth(): number {
  if (props.containerWidth !== undefined) return props.containerWidth
  const container = composerContainer()
  if (container && container.clientWidth > 0) return container.clientWidth
  // 兜底：向上最多 4 层找第一个非 0 宽度（展厅/嵌入场景里可能没有 composer 容器）。
  let node: HTMLElement | null = root.value?.parentElement ?? null
  for (let depth = 0; node && depth < 4; depth += 1) {
    if (node.clientWidth > 0) return node.clientWidth
    node = node.parentElement
  }
  return 0
}

// user:“为什么有那个小竖杠”+
// (那条竖杠来自“窄档”——单个按钮 + 菜单的形态，本该只在放不下时出现。
//  它之所以一直卡在窄档，是因为上一版有一条“自己量自己、太窄就降一档”的自救逻辑：
//  量到的是自己收缩后的宽度（122px / 60px），永远小于一档需要的 274px，于是宿主变宽也回不来。
//  现在只按**宿主宽度**判定，宿主量不到（0）时保持当前档位，不凭 0 猜、也不自己给自己降档)。
function measure() {
  const available = containerWidth()
  if (available > 0) {
    const next = runModeTier(available)
    if (next !== tier.value) {
      tier.value = next
      // 只在开发版留一行证据（前端日志只收 warn/error，所以用 console.error）。
      if (import.meta.env?.DEV) console.error('[run-mode] tier', { tier: next, available })
    }
  }
  if (tier.value !== 'icon') menuOpen.value = false
  observeContainer()
}

// user:“ResizeObserver 要观察那个被选中的容器（不是胶囊自身），并在切换观察目标时断开旧的”。
let observer: ResizeObserver | null = null
let observedTarget: HTMLElement | null = null
function observeContainer() {
  if (typeof ResizeObserver === 'undefined' || !root.value) return
  const target = composerContainer() ?? root.value.parentElement ?? null
  if (!target || target === observedTarget) return
  if (!observer) observer = new ResizeObserver(measure)
  observer.disconnect()
  observer.observe(target)
  observedTarget = target
}

onMounted(() => {
  measure()
  observeContainer()
  window.addEventListener('resize', measure, { passive: true })
})
onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  observedTarget = null
  window.removeEventListener('resize', measure)
})

function pick(value: CoreRunMode) {
  menuOpen.value = false
  emit('update:modelValue', value)
}
const emit = defineEmits<{ 'update:modelValue': [value: CoreRunMode] }>()
</script>

<style scoped>
/* user:“这个空间怎么看也不像会互相挤，肯定是哪里有问题”“为什么有那个小竖杠”+
   (胶囊装的是空会话引导块，空间够就按改造前的原样显示：两格等宽 132px、字号 15px、选中=底色块。
    只有真的放不下时才收紧成二档、再收成一个按钮；那条 2px 竖条是多余的装饰，已删除)。 */
.core-run-mode {
  display: flex;
  max-width: 100%;
  flex: 0 1 auto;
  justify-content: center;
  --text: var(--theme-main-text);
}

.core-run-mode__bar {
  display: inline-flex;
  min-width: 0;
  max-width: 100%;
  align-items: stretch;
  gap: 2px;
  padding: var(--space-1);
  border-radius: var(--radius-pill, 999px);
  background: color-mix(in srgb, var(--text) 8%, transparent);
}

.core-run-mode--locked .core-run-mode__bar {
  padding: 0;
  background: transparent;
}

.core-run-mode__pill {
  /* 一档是改造前的原样：两格等宽 132px、字号 15px，空间够就不压缩。 */
  flex: 0 0 132px;
  height: 40px;
  padding: 0 var(--space-4, 16px);
  overflow: hidden;
  border: 0;
  border-radius: var(--radius-pill, 999px);
  background: transparent;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font: inherit;
  font-size: 15px;
  font-weight: 550;
  letter-spacing: 0.01em;
  white-space: nowrap;
  text-align: center;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

/* user:“中等宽度：两格仍并排，文字可截断（text-overflow: ellipsis），padding 收紧”+ */
.core-run-mode__label {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-run-mode__pill:hover {
  color: color-mix(in srgb, var(--text) 88%, transparent);
  background: color-mix(in srgb, var(--text) 6%, transparent);
}

/* 选中格：只用底色块 + 更亮的字（与改造前一致；不加任何额外指示条/竖杠）。 */
.core-run-mode__pill.is-active {
  background: color-mix(in srgb, var(--text) 16%, transparent);
  color: color-mix(in srgb, var(--text) 98%, transparent);
}

.core-run-mode--locked .core-run-mode__pill,
.core-run-mode--locked .core-run-mode__pill.is-active {
  flex: 0 1 auto;
  background: color-mix(in srgb, var(--text) 10%, transparent);
  color: color-mix(in srgb, var(--text) 72%, transparent);
  cursor: default;
}

.core-run-mode__pill:focus-visible,
.core-run-mode__trigger:focus-visible,
.core-run-mode__menu-item:focus-visible {
  outline: var(--focus-ring-width) solid color-mix(in srgb, var(--text) 30%, transparent);
  outline-offset: var(--focus-ring-offset, 2px);
}

/* 二档：两格仍并排，但可以收——每格 4em 起、字号收紧、文字可省略。
   （只有可用宽度真的小于一档需要的 274px 时才会进入这一档。） */
.core-run-mode--compact .core-run-mode__pill {
  flex: 1 1 0;
  min-width: 4em;
  padding: 0 var(--space-2);
  font-size: var(--type-sm);
  font-weight: 500;
}

/* 三档：只剩一个按钮 + 菜单，两格在这一档不渲染。 */
.core-run-mode__compact {
  position: relative;
  min-width: 0;
  max-width: 100%;
}

.core-run-mode__trigger {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: var(--space-1);
  height: 32px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-pill, 999px);
  background: color-mix(in srgb, var(--text) 12%, transparent);
  color: color-mix(in srgb, var(--text) 92%, transparent);
  font: inherit;
  font-size: var(--type-sm);
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}
.core-run-mode__trigger:hover,
.core-run-mode__trigger.is-open {
  background: color-mix(in srgb, var(--text) 18%, transparent);
}
/* 窄档也只用底色表达当前项：图标 + 当前项文字已经够了，不再加竖条装饰。 */
.core-run-mode__trigger > svg {
  flex: 0 0 auto;
}
.core-run-mode__current {
  max-width: 6em;
}

.core-run-mode__menu {
  position: absolute;
  bottom: calc(100% + var(--space-1));
  left: 0;
  z-index: var(--z-popover, 60);
  display: grid;
  gap: 2px;
  min-width: 8em;
  max-width: min(220px, 60vw);
  margin: 0;
  padding: var(--space-1);
  list-style: none;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: var(--theme-composer-background);
  color: var(--theme-composer-text);
  box-shadow: var(--shadow-sm);
}

.core-run-mode__menu-item {
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: var(--type-sm);
  text-align: left;
  cursor: pointer;
}
.core-run-mode__menu-item:hover {
  background: color-mix(in srgb, var(--text) 10%, transparent);
}
.core-run-mode__menu-item.is-active {
  background: color-mix(in srgb, var(--text) 14%, transparent);
  font-weight: 550;
}
</style>
