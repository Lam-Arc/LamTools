<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="guide-root"
      :class="{ 'is-browsing': browsing }"
      :style="themeStyle"
      :data-guide-active="active ? 'true' : 'false'"
    >
      <!-- 遮罩：聚光灯周围四块挡板。中间那个洞什么都不盖，被指到的真按钮还能点。 -->
      <template v-if="hole && !browsing">
        <div class="guide-blocker" :style="blockerTop" aria-hidden="true"></div>
        <div class="guide-blocker" :style="blockerBottom" aria-hidden="true"></div>
        <div class="guide-blocker" :style="blockerLeft" aria-hidden="true"></div>
        <div class="guide-blocker" :style="blockerRight" aria-hidden="true"></div>
        <div class="guide-hole" :style="holeStyle" aria-hidden="true"></div>
        <div class="guide-hole-ring" :style="holeStyle" aria-hidden="true"></div>
      </template>
      <div v-else-if="!browsing" class="guide-blocker guide-blocker--full" aria-hidden="true"></div>

      <div v-if="!browsing" class="guide-arrow" :style="arrowStyle" aria-hidden="true"></div>

      <Transition v-if="!browsing" name="guide-card" mode="out-in">
        <!-- 入场：先问一句，再决定讲多细。 -->
        <section v-if="!active" key="intro" class="guide-card guide-card--intro" role="dialog" aria-modal="true" :aria-label="t('新手引导')">
          <header class="guide-intro-head">
            <span class="guide-mark" aria-hidden="true">
              <span class="guide-mark-core"></span>
              <span class="guide-mark-ring"></span>
            </span>
            <div>
              <p class="guide-kicker">{{ t("周日的第一课") }}</p>
              <h1 class="guide-title">{{ t("花十分钟，把 Sunday 用明白") }}</h1>
            </div>
          </header>
          <p class="guide-body">
            {{ t("我会先教你点鼠标、打字这些最基础的动作，再指着屏幕上真的按钮讲一遍，最后用一段不联网的练习会话，把「你说话、我干活、关键处问你」整条路走给你看。") }}
          </p>
          <ul class="guide-bullets">
            <li v-for="item in introPoints" :key="item"><Check :size="13" :stroke-width="2.4" aria-hidden="true" /><span>{{ item }}</span></li>
          </ul>
          <div class="guide-intro-actions">
            <button class="guide-button guide-button--primary" type="button" data-guide-start-beginner @click="start('full', true)">
              {{ t("我没怎么用过电脑，从头教") }}
            </button>
            <button class="guide-button" type="button" data-guide-start-quick @click="start('quick', false)">
              {{ t("我用过电脑，讲重点") }}
            </button>
          </div>
          <div class="guide-intro-foot">
            <button v-if="canResume" class="guide-text-button" type="button" @click="resume()">
              {{ t("接着上次继续") }}
            </button>
            <button class="guide-text-button" type="button" @click="dismiss">{{ t("今天先不用") }}</button>
          </div>
        </section>

        <!-- 正片：一句话一张卡，指哪讲哪。 -->
        <section
          v-else-if="current"
          :key="current.step.id"
          ref="cardEl"
          class="guide-card"
          :class="{ 'guide-card--wide': current.step.kind === 'demo' }"
          :style="cardStyle"
          role="dialog"
          aria-modal="false"
          :aria-label="current.step.title"
          tabindex="-1"
          @keydown="onKeydown"
        >
          <header class="guide-card-head">
            <span class="guide-chapter">
              {{ t("第 {0} 章 · {1}", { 0: current.chapterIndex + 1, 1: current.chapterTitle }) }}
            </span>
            <span class="guide-count">{{ current.ordinal }} / {{ current.total }}</span>
            <button class="guide-close" type="button" :aria-label="t('退出引导')" :title="t('退出引导（Esc）')" @click="dismiss">
              <X :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </header>

          <div class="guide-progress" aria-hidden="true"><span :style="{ width: progressPercent }"></span></div>

          <div class="guide-card-body">
            <GuideStoryArt v-if="current.step.kind === 'story'" :scene="storyScene" />

            <h2 class="guide-title">{{ current.step.title }}</h2>
            <p class="guide-body">{{ current.step.body }}</p>

            <ul v-if="storyBullets.length" class="guide-bullets">
              <li v-for="item in storyBullets" :key="item">
                <Check :size="13" :stroke-width="2.4" aria-hidden="true" /><span>{{ item }}</span>
              </li>
            </ul>

            <GuidePractice
              v-if="current.step.kind === 'practice'"
              :key="current.step.id"
              :exercise="practiceExercise"
              @done="practiceDone = true"
            />

            <GuideDemoSession
              v-if="current.step.kind === 'demo'"
              :key="current.step.id"
              @done="next"
            />

            <p v-if="current.step.hint" class="guide-hint">{{ current.step.hint }}</p>

            <!-- 找不到目标时不要把用户扔在空屏上：说清楚，并给一条往前走的路。 -->
            <p v-if="targetMissing" class="guide-missing">
              {{ t("这个按钮现在不在屏幕上，可能是窗口太小或当前页面不同。你可以先继续，等回到主界面再看。") }}
            </p>
          </div>

          <footer class="guide-card-foot">
            <button class="guide-text-button" type="button" :disabled="isFirst" @click="back">{{ t("上一句") }}</button>
            <span class="guide-foot-spacer"></span>
            <button class="guide-text-button" type="button" @click="skipChapter">
              {{ t("跳过这章") }}
            </button>
            <button
              v-if="showConfigureProvider"
              class="guide-button"
              type="button"
              @click="emit('configure-provider')"
            >
              {{ t("现在去配置") }}
            </button>
            <button
              v-if="spotlightOpenArea"
              class="guide-button"
              type="button"
              @click="openArea"
            >
              {{ spotlightOpenLabel || t("进去看一眼") }}
            </button>
            <span v-if="nextBlocked" class="guide-block-note">{{ t("先做完上面的小练习") }}</span>
            <button
              v-if="current.step.kind !== 'demo'"
              class="guide-button guide-button--primary"
              type="button"
              data-guide-next
              :disabled="nextBlocked"
              @click="next"
            >
              {{ isLast ? t("开始用") : waitForClick ? t("我点到了，继续") : t("继续") }}
            </button>
          </footer>

          <p v-if="waitForClick && !nextBlocked" class="guide-wait">
            <span class="guide-wait-dot" aria-hidden="true"></span>{{ t("请直接点上面高亮的地方") }}
          </p>
        </section>
      </Transition>

      <!-- 带用户去别的分区时先让路：整页都能摸，回来只需按一下。 -->
      <div v-if="browsing" class="guide-resume-pill">
        <span>{{ t("随便看，看完回来") }}</span>
        <button type="button" class="guide-button guide-button--primary" @click="browsing = false">
          {{ t("回到引导") }}
        </button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, X } from 'lucide-vue-next'
import { themeToCSSVars, type ThemeData } from '@/helpers/theme.ts'
import GuidePractice from '@/guide/GuidePractice.vue'
import GuideDemoSession from '@/guide/GuideDemoSession.vue'
import GuideStoryArt from '@/guide/GuideStoryArt.vue'
import { useGuide, readGuideMemory, writeGuideMemory } from '@/guide/useGuide.ts'
import type { GuideArea, GuideMode, GuidePlacement, GuideScene } from '@/guide/types.ts'

/**
 * 引导的舞台。
 *
 * user:“诉求是让哪怕没接触过电脑的小白也能用明白sunday”+
 * (两点是硬要求：讲的东西必须在屏幕上真实存在，所以用聚光灯指向真控件；
 *  每一步都要能退，所以永远有上一句、跳过这章、右上角关闭。)
 *
 * user:“流程与展示方式自主设计”+
 * (形式是「一段一段的卡片 + 一个会挖洞的遮罩」：卡片负责说话，遮罩负责把
 *  注意力钉在真实按钮上。剧场那一步单独放大，因为要看的是整段对话。)
 */

const props = defineProps<{
  hasProvider: boolean
  theme: ThemeData
}>()

const emit = defineEmits<{
  'open-area': [area: GuideArea]
  'configure-provider': []
  closed: []
}>()

const guide = useGuide()
const visible = ref(false)
const intro = ref(true)
const cardEl = ref<HTMLElement | null>(null)
const practiceDone = ref(false)
/** 点「进去看一眼」后暂时收起引导，让用户真的能操作那个分区。 */
const browsing = ref(false)
const hole = ref<{ x: number; y: number; w: number; h: number } | null>(null)
const targetMissing = ref(false)
const cardBox = ref({ w: 400, h: 320 })
const viewport = ref({ w: 1280, h: 800 })
const canResume = ref(false)

const active = computed(() => visible.value && !intro.value)
const current = computed(() => guide.current.value)
const isFirst = computed(() => guide.isFirst.value)
const isLast = computed(() => guide.isLast.value)
const progressPercent = computed(() => `${Math.round(guide.progress.value * 100)}%`)
const themeStyle = computed<Record<string, string>>(() => ({ ...themeToCSSVars(props.theme) }))

/** 零基础练习必须先完成；其余步骤永远放行。 */
const nextBlocked = computed(() => {
  const step = current.value?.step
  return step?.kind === 'practice' && !practiceDone.value
})
const waitForClick = computed(() => current.value?.step.kind === 'spotlight' && Boolean(current.value.step.waitForClick))

// 模板里直接做联合类型收窄在 vue-tsc 下不稳，统一在这里取好。
const storyScene = computed<GuideScene>(() => {
  const step = current.value?.step
  return step?.kind === 'story' ? step.scene : 'welcome'
})
const storyBullets = computed<string[]>(() => {
  const step = current.value?.step
  return step?.kind === 'story' ? step.bullets ?? [] : []
})
const practiceExercise = computed<'click' | 'type' | 'scroll'>(() => {
  const step = current.value?.step
  return step?.kind === 'practice' ? step.exercise : 'click'
})
const spotlightTarget = computed(() => {
  const step = current.value?.step
  return step?.kind === 'spotlight' ? step.target : ''
})
const spotlightPlacement = computed<GuidePlacement>(() => {
  const step = current.value?.step
  return step?.kind === 'spotlight' ? step.placement ?? 'auto' : 'auto'
})
const spotlightOpenArea = computed<GuideArea | null>(() => {
  const step = current.value?.step
  return step?.kind === 'spotlight' ? step.openArea ?? null : null
})
const spotlightOpenLabel = computed(() => {
  const step = current.value?.step
  return step?.kind === 'spotlight' ? step.openLabel ?? '' : ''
})
const showConfigureProvider = computed(() => current.value?.step.id === 'provider-missing')

const introPoints = computed(() => [
  t("全部在本机演，不花你的额度"),
  t("每一步都能跳过，随时按 Esc 退出"),
  t("走完以后点左边的「?」还能再看"),
])

function start(mode: GuideMode, beginner: boolean): void {
  intro.value = false
  practiceDone.value = false
  guide.begin({ mode, beginner, hasProvider: props.hasProvider })
  visible.value = true
  void nextTick(() => cardEl.value?.focus({ preventScroll: true }))
}

function resume(): void {
  intro.value = false
  practiceDone.value = false
  guide.resume(props.hasProvider)
  visible.value = true
  void nextTick(() => cardEl.value?.focus({ preventScroll: true }))
}

function dismiss(): void {
  if (active.value) {
    guide.stop()
  } else {
    // 在选择页就退出：算“今天先不用”，不再每次启动都拦一次；入口仍然常驻。
    writeGuideMemory({ completed: true })
  }
  browsing.value = false
  visible.value = false
  emit('closed')
}

function next(): void {
  if (nextBlocked.value) return
  practiceDone.value = false
  guide.next()
  if (!guide.active.value) {
    visible.value = false
    emit('closed')
  }
}

function back(): void {
  practiceDone.value = false
  guide.back()
}

function skipChapter(): void {
  practiceDone.value = false
  guide.skipChapter()
  if (!guide.active.value) {
    visible.value = false
    emit('closed')
  }
}

function openArea(): void {
  if (!spotlightOpenArea.value) return
  emit('open-area', spotlightOpenArea.value)
  browsing.value = true
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    dismiss()
    return
  }
  const target = event.target as HTMLElement | null
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
  if (event.key === 'ArrowRight' || event.key === 'Enter') {
    event.preventDefault()
    if (current.value?.step.kind !== 'demo') next()
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    back()
  }
}

// ── 目标测量 ────────────────────────────────────────────────────────────────
// 真控件会动：会话栏折叠、菜单弹出、窗口缩放都会改变位置。用轻量轮询而不是
// 一次性测量，保证高亮框一直贴着按钮；找不到就明确告诉用户，不假装指着东西。

let poll: ReturnType<typeof setInterval> | null = null

function measure(): void {
  // 卡片自身的尺寸要先量：剧场那一步比普通卡片高得多，用旧高度算位置会顶出屏幕。
  const cardNode = cardEl.value
  if (cardNode) {
    const width = cardNode.offsetWidth
    const height = cardNode.offsetHeight
    if (width > 0 && height > 0 && (width !== cardBox.value.w || height !== cardBox.value.h)) {
      cardBox.value = { w: width, h: height }
    }
  }
  viewport.value = { w: window.innerWidth, h: window.innerHeight }

  const target = spotlightTarget.value
  if (!target) {
    hole.value = null
    targetMissing.value = false
    return
  }
  const element = document.querySelector(target) as HTMLElement | null
  if (!element) {
    hole.value = null
    targetMissing.value = true
    return
  }
  const rect = element.getBoundingClientRect()
  if (rect.width < 2 || rect.height < 2) {
    hole.value = null
    targetMissing.value = true
    return
  }
  targetMissing.value = false
  const pad = 8
  hole.value = {
    x: Math.max(0, rect.left - pad),
    y: Math.max(0, rect.top - pad),
    w: Math.min(window.innerWidth, rect.right + pad) - Math.max(0, rect.left - pad),
    h: Math.min(window.innerHeight, rect.bottom + pad) - Math.max(0, rect.top - pad),
  }
  cardBox.value = {
    w: cardEl.value?.offsetWidth || 400,
    h: cardEl.value?.offsetHeight || 320,
  }
  viewport.value = { w: window.innerWidth, h: window.innerHeight }
}

function startPolling(): void {
  stopPolling()
  measure()
  void nextTick(measure)
  poll = setInterval(measure, 220)
}

function stopPolling(): void {
  if (poll) clearInterval(poll)
  poll = null
}

watch(
  () => current.value?.step.id,
  () => {
    practiceDone.value = false
    startPolling()
  },
)

// 等待点击：点中高亮目标就自动前进；点别处不判错，只是没反应。
function onDocumentClick(event: MouseEvent): void {
  if (!active.value) return
  const step = current.value?.step
  if (!step || step.kind !== 'spotlight' || !step.waitForClick) return
  const target = event.target as Element | null
  if (target?.closest?.(step.target)) next()
}

onMounted(() => {
  const memory = readGuideMemory()
  canResume.value = Boolean(memory.stepId) && !memory.completed
  document.addEventListener('click', onDocumentClick, true)
  document.addEventListener('keydown', onDocumentEscape)
  window.addEventListener('resize', measure)
  window.addEventListener('scroll', measure, true)
})

onBeforeUnmount(() => {
  stopPolling()
  document.removeEventListener('click', onDocumentClick, true)
  document.removeEventListener('keydown', onDocumentEscape)
  window.removeEventListener('resize', measure)
  window.removeEventListener('scroll', measure, true)
})

/** 只看不点的时候（browsing）卡片不在，Esc 也应该能收回来。 */
function onDocumentEscape(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !visible.value) return
  if (browsing.value) {
    event.preventDefault()
    browsing.value = false
  }
}

// 只有引导真的开着时才轮询目标位置；平时不占帧。
watch([visible, active], ([shown, running]) => {
  if (shown && running) startPolling()
  else stopPolling()
})

// 卡片尺寸变化（练习区出现、剧场展开）后重新定位。
watch(
  () => current.value?.step.kind,
  () => void nextTick(measure),
)

// ── 位置计算 ────────────────────────────────────────────────────────────────

const holeStyle = computed(() => {
  const box = hole.value
  if (!box) return {}
  return {
    left: `${box.x}px`,
    top: `${box.y}px`,
    width: `${box.w}px`,
    height: `${box.h}px`,
  }
})

const blockerTop = computed(() => {
  const box = hole.value
  if (!box) return {}
  return { left: '0px', top: '0px', width: '100vw', height: `${box.y}px` }
})
const blockerBottom = computed(() => {
  const box = hole.value
  if (!box) return {}
  return { left: '0px', top: `${box.y + box.h}px`, width: '100vw', height: `calc(100vh - ${box.y + box.h}px)` }
})
const blockerLeft = computed(() => {
  const box = hole.value
  if (!box) return {}
  return { left: '0px', top: `${box.y}px`, width: `${box.x}px`, height: `${box.h}px` }
})
const blockerRight = computed(() => {
  const box = hole.value
  if (!box) return {}
  return { left: `${box.x + box.w}px`, top: `${box.y}px`, width: `calc(100vw - ${box.x + box.w}px)`, height: `${box.h}px` }
})

interface Placement {
  left: number
  top: number
  side: 'top' | 'bottom' | 'left' | 'right' | 'center'
}

const placement = computed<Placement>(() => {
  const box = hole.value
  const vw = viewport.value.w
  const vh = viewport.value.h
  const cw = Math.min(cardBox.value.w || 400, vw - 32)
  const ch = cardBox.value.h || 320
  const gap = 18

  if (!box) {
    return { left: (vw - cw) / 2, top: Math.max(16, (vh - ch) / 2), side: 'center' }
  }

  const clampX = (value: number) => Math.min(Math.max(16, value), Math.max(16, vw - cw - 16))
  const clampY = (value: number) => Math.min(Math.max(16, value), Math.max(16, vh - ch - 16))
  const prefer = spotlightPlacement.value
  const roomTop = box.y
  const roomBottom = vh - (box.y + box.h)
  const roomRight = vw - (box.x + box.w)
  const roomLeft = box.x

  const wantsTop = prefer === 'top'
  const wantsBottom = prefer === 'bottom'
  const wantsRight = prefer === 'right'
  const wantsLeft = prefer === 'left'

  if (wantsRight && roomRight >= cw + gap) {
    return { left: box.x + box.w + gap, top: clampY(box.y + box.h / 2 - ch / 2), side: 'right' }
  }
  if (wantsLeft && roomLeft >= cw + gap) {
    return { left: box.x - cw - gap, top: clampY(box.y + box.h / 2 - ch / 2), side: 'left' }
  }
  if (wantsTop && roomTop >= ch + gap) {
    return { left: clampX(box.x + box.w / 2 - cw / 2), top: box.y - ch - gap, side: 'top' }
  }
  if (wantsBottom && roomBottom >= ch + gap) {
    return { left: clampX(box.x + box.w / 2 - cw / 2), top: box.y + box.h + gap, side: 'bottom' }
  }

  // 自动：上下优先，其次左右，最后居中。
  if (roomBottom >= ch + gap) {
    return { left: clampX(box.x + box.w / 2 - cw / 2), top: box.y + box.h + gap, side: 'bottom' }
  }
  if (roomTop >= ch + gap) {
    return { left: clampX(box.x + box.w / 2 - cw / 2), top: box.y - ch - gap, side: 'top' }
  }
  if (roomRight >= cw + gap) {
    return { left: box.x + box.w + gap, top: clampY(box.y + box.h / 2 - ch / 2), side: 'right' }
  }
  if (roomLeft >= cw + gap) {
    return { left: box.x - cw - gap, top: clampY(box.y + box.h / 2 - ch / 2), side: 'left' }
  }
  return { left: (vw - cw) / 2, top: Math.max(16, (vh - ch) / 2), side: 'center' }
})

const cardStyle = computed(() => ({
  left: `${placement.value.left}px`,
  top: `${placement.value.top}px`,
}))

const arrowStyle = computed(() => {
  const box = hole.value
  if (!box) return { display: 'none' }
  const side = placement.value.side
  const card = placement.value
  const cw = Math.min(cardBox.value.w || 400, viewport.value.w - 32)
  const ch = cardBox.value.h || 320
  const midX = box.x + box.w / 2
  const midY = box.y + box.h / 2
  const clamp = (v: number, min: number, max: number) => Math.min(Math.max(v, min), max)
  if (side === 'bottom') return { left: `${clamp(midX, card.left + 20, card.left + cw - 20)}px`, top: `${card.top - 7}px` }
  if (side === 'top') return { left: `${clamp(midX, card.left + 20, card.left + cw - 20)}px`, top: `${card.top + ch - 7}px` }
  if (side === 'right') return { left: `${card.left - 7}px`, top: `${clamp(midY, card.top + 20, card.top + ch - 20)}px` }
  if (side === 'left') return { left: `${card.left + cw - 7}px`, top: `${clamp(midY, card.top + 20, card.top + ch - 20)}px` }
  return { display: 'none' }
})

/** 从左竖栏的「?」打开：先给出“从头教 / 讲重点 / 接着上次”的选择。 */
function open(): void {
  const memory = readGuideMemory()
  canResume.value = Boolean(memory.stepId) && !memory.completed
  visible.value = true
  intro.value = true
  stopPolling()
}

/**
 * 首次进入时自动拉起。
 * 有没走完的进度就直接续上；没动过就停在选择页，避免硬塞给用户一段长教程。
 */
function autoStart(): void {
  const memory = readGuideMemory()
  if (memory.completed) return
  visible.value = true
  intro.value = true
  canResume.value = Boolean(memory.stepId)
}

defineExpose({ open, autoStart, dismiss })
</script>

<style scoped>
.guide-root {
  position: fixed;
  inset: 0;
  z-index: var(--z-fullscreen, 900);
  pointer-events: none;
  --text: var(--theme-main-text, #fbf7f0);
  color: var(--text);
  font-family: var(--font-sans);
}

.guide-blocker {
  position: fixed;
  pointer-events: auto;
  background: rgba(6, 7, 9, .55);
  backdrop-filter: blur(2px);
  animation: guide-fade-in .2s ease-out;
}

.guide-blocker--full {
  inset: 0;
}

.guide-hole {
  position: fixed;
  border-radius: var(--radius);
  box-shadow: 0 0 0 9999px transparent;
  pointer-events: none;
}

.guide-hole-ring {
  position: fixed;
  border: 1px solid color-mix(in srgb, var(--text) 55%, transparent);
  border-radius: var(--radius);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--text) 12%, transparent), 0 0 26px color-mix(in srgb, var(--text) 10%, transparent);
  pointer-events: none;
  animation: guide-breathe 2.6s ease-in-out infinite;
}

.guide-arrow {
  position: fixed;
  width: 12px;
  height: 12px;
  border: 1px solid color-mix(in srgb, var(--text) 18%, transparent);
  background: var(--theme-main-background, #1b1d22);
  transform: rotate(45deg);
  pointer-events: none;
}

.guide-card {
  position: fixed;
  pointer-events: auto;
  display: grid;
  width: min(400px, calc(100vw - 32px));
  max-height: min(78vh, 720px);
  overflow: hidden;
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--text) 12%, transparent));
  border-radius: var(--radius-lg);
  background: var(--theme-main-background, #1b1d22);
  box-shadow: var(--shadow-lg);
  color: var(--text);
  outline: none;
}

/* 头、进度、正文、按钮四段：只有正文滚动，走到底也能看见「继续」。 */
.guide-card:not(.guide-card--intro) {
  grid-template-rows: auto auto minmax(0, 1fr) auto;
}

.guide-card--wide {
  width: min(760px, calc(100vw - 32px));
}

.guide-card--intro {
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: min(520px, calc(100vw - 32px));
  max-height: calc(100vh - 32px);
  padding: var(--space-5);
  gap: var(--space-3);
  overflow-y: auto;
}

.guide-card-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4) 0;
}

.guide-chapter {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11.5px;
  font-weight: 650;
  letter-spacing: .01em;
  color: color-mix(in srgb, var(--text) 52%, transparent);
}

.guide-count {
  flex: 0 0 auto;
  margin-left: auto;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--text) 34%, transparent);
}

.guide-close {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 46%, transparent);
  cursor: pointer;
}

.guide-close:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover, 8%), transparent);
  color: var(--text);
}

.guide-progress {
  height: 2px;
  margin: var(--space-2) var(--space-4) 0;
  background: color-mix(in srgb, var(--text) 16%, transparent);
  border-radius: 1px;
  overflow: hidden;
}

.guide-progress span {
  display: block;
  height: 100%;
  background: color-mix(in srgb, var(--text) 74%, transparent);
  transition: width .3s var(--ease-out, ease-out);
}

.guide-card-body {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  overflow-y: auto;
  scrollbar-width: thin;
}

.guide-card--wide .guide-card-body {
  padding-bottom: var(--space-2);
}

.guide-title {
  margin: 0;
  font-size: 20px;
  font-weight: 730;
  letter-spacing: -0.02em;
  line-height: 1.3;
  text-wrap: balance;
}

.guide-body {
  margin: 0;
  font-size: 14px;
  line-height: 1.75;
  color: color-mix(in srgb, var(--text) 76%, transparent);
}

.guide-hint {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: color-mix(in srgb, var(--text) 46%, transparent);
}

.guide-missing {
  margin: 0;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--orange) 12%, transparent);
  font-size: 12.5px;
  line-height: 1.6;
  color: color-mix(in srgb, var(--text) 78%, transparent);
}

.guide-bullets {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.guide-bullets li {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-size: 13px;
  line-height: 1.6;
  color: color-mix(in srgb, var(--text) 66%, transparent);
}

.guide-bullets li :deep(svg) {
  margin-top: 4px;
  flex: 0 0 auto;
  color: var(--green);
}

.guide-card-foot {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4) var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--text) 8%, transparent);
}

.guide-foot-spacer {
  flex: 1 1 auto;
}

.guide-button {
  min-height: 32px;
  padding: 0 var(--space-3);


  background: color-mix(in srgb, var(--text) var(--alpha-hover, 8%), transparent);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  font-weight: 640;

  transition: background var(--dur-fast, .16s) var(--ease-out, ease-out), filter var(--dur-fast, .16s) var(--ease-out, ease-out);
}

.guide-button:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-active, 12%), transparent);
}

.guide-button--primary {
  background: var(--theme-control-solid, #fbf7f0);
  color: var(--theme-control-text, #2e3138);
}

.guide-button--primary:hover {
  filter: brightness(.94);
}

.guide-button:disabled {
  cursor: default;
  opacity: .45;
}

/* 主按钮禁用时不要只降透明度：象牙色底降到 45% 还是亮的，看起来照样能按。
   直接换成低对比的底与字，让“还不能点”一眼可见。 */
.guide-button--primary:disabled {
  opacity: 1;
  background: color-mix(in srgb, var(--text) 9%, transparent);
  color: color-mix(in srgb, var(--text) 38%, transparent);
  filter: none;
}

.guide-block-note {
  margin-right: var(--space-1);
  font-size: 11.5px;
  color: color-mix(in srgb, var(--text) 38%, transparent);
}

.guide-text-button {
  border: 0;
  padding: 4px 2px;
  background: transparent;
  color: color-mix(in srgb, var(--text) 44%, transparent);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.guide-text-button:hover:not(:disabled) {
  color: color-mix(in srgb, var(--text) 76%, transparent);
}

.guide-text-button:disabled {
  opacity: .35;
  cursor: default;
}

.guide-wait {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 0 var(--space-4) var(--space-3);
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 46%, transparent);
}

.guide-wait-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--decision-attention, #b49a60);
  animation: guide-pulse 1.6s ease-out infinite;
}

/* 入场 */
.guide-intro-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.guide-kicker {
  margin: 0 0 2px;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--text) 40%, transparent);
}

.guide-mark {
  position: relative;
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
}

.guide-mark-core {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--text);
  box-shadow: 0 0 18px color-mix(in srgb, var(--text) 40%, transparent);
}

.guide-mark-ring {
  position: absolute;
  inset: 4px;
  border: 1px solid color-mix(in srgb, var(--text) 26%, transparent);
  border-radius: 50%;
  animation: guide-breathe 3.4s ease-in-out infinite;
}

.guide-intro-actions {
  display: grid;
  gap: var(--space-2);
}

.guide-intro-actions .guide-button {
  min-height: 40px;
  font-size: 14px;
}

.guide-intro-foot {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
}

.guide-card.guide-card--intro .guide-title {
  font-size: 21px;
}

/* 进出场 */
.guide-card-enter-active,
.guide-card-leave-active {
  transition: opacity .18s var(--ease-out, ease-out), transform .18s var(--ease-out, ease-out);
}

.guide-card-enter-from,
.guide-card-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

.guide-card--intro.guide-card-enter-from,
.guide-card--intro.guide-card-leave-to {
  transform: translate(-50%, calc(-50% + 6px));
}

@keyframes guide-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes guide-breathe {
  0%, 100% { opacity: .55; }
  50% { opacity: 1; }
}

@keyframes guide-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--decision-attention, #b49a60) 55%, transparent); }
  100% { box-shadow: 0 0 0 8px transparent; }
}


.guide-resume-pill {
  position: fixed;
  right: var(--space-5);
  bottom: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--text) 14%, transparent));
  border-radius: 999px;
  background: var(--theme-main-background, #1b1d22);
  box-shadow: var(--shadow-lg);
  pointer-events: auto;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--text) 66%, transparent);
}

.guide-resume-pill .guide-button {
  border-radius: 999px;
}

@media (max-width: 640px) {
  .guide-resume-pill {
    left: 16px;
    right: 16px;
    bottom: 16px;
    justify-content: space-between;
  }
}

@media (max-width: 640px) {
  .guide-card {
    left: 16px !important;
    top: auto !important;
    bottom: 16px;
    width: calc(100vw - 32px);
    max-height: 62vh;
  }
  .guide-card--intro {
    top: 50% !important;
    bottom: auto;
    transform: translate(-50%, -50%) !important;
  }
  .guide-arrow { display: none !important; }
}

@media (prefers-reduced-motion: reduce) {
  .guide-hole-ring,
  .guide-mark-ring,
  .guide-wait-dot {
    animation: none;
  }
  .guide-blocker,
  .guide-card-enter-active,
  .guide-card-leave-active {
    animation: none;
    transition: none;
  }
}
</style>
