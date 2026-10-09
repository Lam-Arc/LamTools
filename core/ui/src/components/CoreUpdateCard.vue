<template>
  <Teleport to="body">
    <div ref="scrimEl" class="core-update-scrim" data-update-scrim @click="requestClose" />
    <div
      ref="cardEl"
      class="core-update-card"
      role="dialog"
      aria-modal="true"
      aria-labelledby="core-update-card-title"
      data-update-card
    >
      <header class="core-update-card__head">
        <h3 id="core-update-card-title" class="core-update-card__title">
          {{ headTitle }}
        </h3>
        <button
          class="core-update-card__dismiss"
          type="button"
          :aria-label="installBusy ? '取消更新' : '关闭'"
          data-update-dismiss
          @click="requestCancel"
        >
          <X :size="15" :stroke-width="2" aria-hidden="true" />
        </button>
      </header>

      <p class="core-update-card__versions" data-update-versions>
        <span class="core-update-card__version">{{ currentVersion || '当前版本' }}</span>
        <ArrowRight class="core-update-card__arrow" :size="14" :stroke-width="2" aria-hidden="true" />
        <span class="core-update-card__version core-update-card__version--next">{{ latestVersion || '最新版本' }}</span>
      </p>

      <p v-if="notes" class="core-update-card__notes" data-update-notes>{{ notes }}</p>

      <div v-if="installBusy || downloaded" class="core-update-card__progress" data-update-progress>
        <div class="core-update-card__bar" role="progressbar" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100">
          <span class="core-update-card__fill" :style="{ width: `${percent}%` }" />
        </div>
        <span class="core-update-card__percent" data-update-percent>{{ percentLabel }}</span>
      </div>

      <p v-if="error" class="core-update-card__note core-update-card__note--error" data-update-card-error>{{ error }}</p>
      <p v-else-if="statusLine" class="core-update-card__note" data-update-card-status>{{ statusLine }}</p>

      <footer class="core-update-card__actions">
        <button
          class="core-update-card__btn"
          type="button"
          data-update-cancel
          :disabled="installing"
          @click="requestCancel"
        >{{ cancelLabel }}</button>
        <button
          class="core-update-card__btn core-update-card__btn--primary"
          type="button"
          data-update-confirm
          :disabled="confirmDisabled"
          @click="emit('confirm')"
        >{{ confirmLabel }}</button>
      </footer>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
/**
 * CoreUpdateCard — 应用内更新的卡片。
 *
 * 它是左侧竖栏那枚更新图标「长出来」的样子：点图标时，卡片先被压回按钮那一小块，
 * 再用 back.out 的过冲长到屏幕中央（这点过冲就是用户要的惯性与回弹）。关闭时
 * 原路缩回去。动效全部走 transform（GPU 合成），不碰布局。
 *
 * 卡片只说三件事：从哪个版本到哪个版本、更新摘要（有就显示）、以及此刻走到哪一步
 * （下载百分比 / 正在安装）。「更新」按下之后不再需要第二次点击：下载完成即自动安装，
 * 安装完由安装程序把应用重新拉起来。下载中「取消」真的会停掉传输。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowRight, X } from 'lucide-vue-next'
import { gsap } from 'gsap'

export type CoreUpdateCardState = 'idle' | 'downloading' | 'downloaded' | 'installing' | 'failed'

const props = withDefaults(defineProps<{
  /** 图标元素：卡片从这里长出来、关闭时缩回这里。 */
  origin?: HTMLElement | null
  currentVersion?: string
  latestVersion?: string
  notes?: string
  state?: CoreUpdateCardState
  /** 已下载字节 / 总字节，用来画进度。 */
  received?: number
  total?: number
  progressLabel?: string
  error?: string
}>(), {
  origin: null,
  currentVersion: '',
  latestVersion: '',
  notes: '',
  state: 'idle',
  received: 0,
  total: 0,
  progressLabel: '',
  error: '',
})

const emit = defineEmits<{
  confirm: []
  cancel: []
  closed: []
}>()

const cardEl = ref<HTMLElement | null>(null)
const scrimEl = ref<HTMLElement | null>(null)

const installBusy = computed(() => props.state === 'downloading')
const downloaded = computed(() => props.state === 'downloaded')
const installing = computed(() => props.state === 'installing')

const percent = computed(() => {
  if (props.total > 0) return Math.min(100, Math.max(0, Math.round((props.received / props.total) * 100)))
  return downloaded.value || installing.value ? 100 : 0
})
const percentLabel = computed(() => {
  if (installBusy.value) return props.total > 0 ? `下载 ${percent.value}%` : '下载中'
  if (downloaded.value || installing.value) return '下载完成 100%'
  return ''
})

const headTitle = computed(() => {
  if (installing.value || downloaded.value) return '正在安装更新'
  if (installBusy.value) return '正在下载更新'
  return `发现新版本 v${props.latestVersion || ''}`
})
const statusLine = computed(() => {
  if (installing.value || downloaded.value) return '安装完成后 Sunday 会自动重新打开。'
  if (installBusy.value) return props.progressLabel || ''
  return ''
})
const cancelLabel = computed(() => (installBusy.value ? '取消下载' : '取消'))
const confirmLabel = computed(() => {
  if (installing.value || downloaded.value) return '正在安装…'
  if (installBusy.value) return props.progressLabel ? '下载中' : '下载中…'
  if (props.state === 'failed') return '重试'
  return '更新'
})
const confirmDisabled = computed(() => installBusy.value || downloaded.value || installing.value)

/** 用户在系统里要求减少动效时不做过冲，只做一次短淡入。 */
function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

let context: gsap.Context | null = null
let closing = false

/** 卡片中心相对按钮中心的位移，以及要把卡片压到按钮大小所需的缩放。 */
function morphFrom(origin: HTMLElement, card: HTMLElement) {
  const from = origin.getBoundingClientRect()
  const to = card.getBoundingClientRect()
  return {
    x: from.left + from.width / 2 - (to.left + to.width / 2),
    y: from.top + from.height / 2 - (to.top + to.height / 2),
    scaleX: Math.max(0.06, from.width / to.width),
    scaleY: Math.max(0.06, from.height / to.height),
  }
}

onMounted(() => {
  const card = cardEl.value
  if (!card) return
  context = gsap.context(() => {
    if (prefersReducedMotion() || !props.origin) {
      if (scrimEl.value) gsap.fromTo(scrimEl.value, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.18, ease: 'power1.out' })
      gsap.fromTo(card, { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.22, ease: 'power2.out' })
      return
    }
    const start = morphFrom(props.origin, card)
    if (scrimEl.value) gsap.fromTo(scrimEl.value, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.26, ease: 'power1.out' })
    gsap.set(card, { ...start, autoAlpha: 0.45, transformOrigin: '50% 50%' })
    gsap.to(card, {
      x: 0,
      y: 0,
      scaleX: 1,
      scaleY: 1,
      autoAlpha: 1,
      duration: 0.62,
      ease: 'back.out(1.2)',
      clearProps: 'transformOrigin',
    })
  }, card)
})

onBeforeUnmount(() => {
  context?.revert()
})

/** 缩回按钮那一小块，然后交还宿主（宿主据此卸载卡片）。 */
async function close(): Promise<void> {
  if (closing) return
  closing = true
  const card = cardEl.value
  const origin = props.origin
  if (card && origin && !prefersReducedMotion()) {
    const end = morphFrom(origin, card)
    await new Promise<void>((resolve) => {
      if (scrimEl.value) gsap.to(scrimEl.value, { autoAlpha: 0, duration: 0.3, ease: 'power2.in' })
      gsap.to(card, { ...end, autoAlpha: 0.3, duration: 0.34, ease: 'power3.in', onComplete: resolve })
    })
  }
  emit('closed')
}

function requestCancel(): void {
  // 下载中：「取消」停掉传输再收卡片；安装一旦开始就无法中止，这时只允许看。
  if (installBusy.value) {
    emit('cancel')
    void close()
    return
  }
  if (downloaded.value || installing.value) return
  void close()
}

function requestClose(): void {
  requestCancel()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') requestCancel()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.core-update-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal, 80);
  background: color-mix(in srgb, var(--theme-backdrop-text, var(--text)) 20%, transparent);
}

/* 卡片自己就是构图中心：柔和的大圆角（--radius-xl）、主区底色、最大一档阴影。 */
.core-update-card {
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: calc(var(--z-modal, 80) + 1);
  width: min(420px, calc(100vw - 48px));
  max-height: calc(100vh - 96px);
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 10%, transparent);
  border-radius: var(--radius-xl);
  background: var(--theme-main-background, var(--panel));
  box-shadow: var(--shadow-lg);
  color: var(--theme-main-text, var(--text));
  translate: -50% -50%;
}

.core-update-card__head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
}

.core-update-card__title {
  margin: 0;
  font-size: 14px;
  font-weight: 680;
  line-height: 1.4;
}

.core-update-card__dismiss {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 62%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.core-update-card__dismiss:hover {
  background: color-mix(in srgb, var(--theme-main-text, var(--text)) var(--alpha-hover), transparent);
  color: var(--theme-main-text, var(--text));
}

.core-update-card__versions {
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-variant-numeric: tabular-nums;
}
.core-update-card__version {
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 62%, transparent);
  font-size: 13px;
}
.core-update-card__version--next {
  color: var(--theme-main-text, var(--text));
  font-weight: 650;
}
.core-update-card__arrow {
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 42%, transparent);
}

/* 摘要可能很长：让它自己滚，卡片高度封顶。 */
.core-update-card__notes {
  margin: 0;
  max-height: 34vh;
  overflow-y: auto;
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 72%, transparent);
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.core-update-card__progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
}
.core-update-card__bar {
  height: 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text, var(--text)) 12%, transparent);
  overflow: hidden;
}
.core-update-card__fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--theme-control-background, color-mix(in srgb, var(--theme-main-text, var(--text)) 70%, transparent));
  transition: width 200ms var(--ease-out);
}
.core-update-card__percent {
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 72%, transparent);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.core-update-card__note {
  margin: 0;
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 62%, transparent);
  font-size: 12px;
  line-height: 1.55;
}
.core-update-card__note--error { color: color-mix(in srgb, var(--red) 82%, var(--theme-main-text, var(--text)) 18%); }

.core-update-card__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
.core-update-card__btn {
  min-height: 32px;
  padding: 6px var(--space-3);
  border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 16%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--theme-main-text, var(--text));
  font: inherit;
  font-size: 12.5px;
  font-weight: 650;
  cursor: pointer;
  transition: background-color 140ms ease-out, filter 160ms ease-out;
}
.core-update-card__btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text, var(--text)) var(--alpha-hover), transparent);
}
.core-update-card__btn--primary {
  border-color: transparent;
  background: var(--theme-control-background);
  color: var(--theme-control-text);
}
.core-update-card__btn--primary:hover:not(:disabled) { filter: brightness(.94); }
.core-update-card__btn:disabled { opacity: .45; cursor: default; }
</style>
