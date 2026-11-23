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
      tabindex="-1"
      @keydown.tab="trapDialogTab"
    >
      <header class="core-update-card__head">
        <h3 id="core-update-card-title" class="core-update-card__title">
          {{ headTitle }}
        </h3>
        <button
          class="core-update-card__dismiss"
          type="button"
          :aria-label="t('关闭')"
          data-update-dismiss
          :disabled="installing"
          @click="requestClose"
        >
          <X :size="15" :stroke-width="2" aria-hidden="true" />
        </button>
      </header>

      <p class="core-update-card__versions" data-update-versions>
        <span class="core-update-card__version">{{ currentVersion || t("当前版本") }}</span>
        <ArrowRight class="core-update-card__arrow" :size="14" :stroke-width="2" aria-hidden="true" />
        <span class="core-update-card__version core-update-card__version--next">{{ latestVersion || t("最新版本") }}</span>
      </p>

      <p v-if="notes" class="core-update-card__notes" data-update-notes>{{ notes }}</p>

      <div v-if="installBusy || downloaded" class="core-update-card__progress" data-update-progress>
        <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(未知总量报告为不确定进度，已知总量保留百分比)。 -->
        <SundayProgress class="core-update-card__bar" :value="percent" :max="100" :indeterminate="installBusy && total <= 0" :label="t('更新下载进度')" :value-text="percentLabel" />
        <span class="core-update-card__percent" data-update-percent>{{ percentLabel }}</span>
      </div>

      <p v-if="error" class="core-update-card__note core-update-card__note--error" data-update-card-error>{{ error }}</p>
      <p v-else-if="statusLine" class="core-update-card__note" data-update-card-status>{{ statusLine }}</p>
      <!-- user:“更新时可以后台下载。再次点更新键后的卡片继承进度”+(下载中要说明关掉卡片
           不会打断传输，否则用户会以为点 X 就等于取消，再点一次又从 0 开始)。 -->
      <p v-if="installBusy" class="core-update-card__note" data-update-background-hint>
        {{ t("关掉卡片不会中断下载，可以继续用 Sunday；点左侧的更新图标回来看进度。") }}
      </p>

      <footer class="core-update-card__actions">
        <button
          class="core-update-card__btn"
          type="button"
          data-update-cancel
          :disabled="installing"
          @click="requestCancelDownload"
        >{{ cancelLabel }}</button>
        <button
          class="core-update-card__btn core-update-card__btn--primary"
          type="button"
          data-update-confirm
          :disabled="confirmDisabled"
          @click="emit('confirm')"
        >{{ confirmLabel }}</button>
        <!-- user:“直接渲染项目真实组件”+(展厅可注入结束预览操作，生产更新流程不增加按钮)。 -->
        <slot name="preview-actions" />
      </footer>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

/**
 * CoreUpdateCard — 应用内更新的卡片。
 *
 * 它是左侧竖栏那枚更新图标「长出来」的样子：点图标时，卡片先被压回按钮那一小块，
 * 再用 back.out 的过冲长到屏幕中央（这点过冲就是用户要的惯性与回弹）。关闭时
 * 原路缩回去。动效全部走 transform（GPU 合成），不碰布局。
 *
 * 卡片只说三件事：从哪个版本到哪个版本、更新摘要（有就显示）、以及此刻走到哪一步
 * （下载百分比 / 正在安装）。下载属于后台：关掉卡片不会打断传输，再打开接上同一条
 * 进度；只有「取消下载」会真的停掉它。卡片还开着时下载完成即自动安装，安装完由安装
 * 程序把应用重新拉起来。
 */
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowRight, X } from 'lucide-vue-next'
import { gsap } from 'gsap'
// user:“动画什么的可复用性，像是下载窗口弹出的那个动画”+(形变参数与守卫收进 presets，组件只声明从哪长出来)
import { enterFade, enterMorph, enterScrim, leaveMorph, leaveScrim, shouldSkipMotion } from '@/motion/presets.ts'
import { trapDialogTab } from '@/composables/trapDialogTab.ts'
import SundayProgress from '@/components/SundayProgress.vue'

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
  if (installBusy.value) return props.total > 0 ? t("下载 {0}%", { 0: percent.value }) : t("下载中")
  if (downloaded.value || installing.value) return t("下载完成 100%")
  return ''
})

const headTitle = computed(() => {
  if (installing.value) return t("正在安装更新")
  if (downloaded.value) return t("更新已就绪")
  if (installBusy.value) return t("正在下载更新")
  return t("发现新版本 v{0}", { 0: props.latestVersion || '' })
})
const statusLine = computed(() => {
  if (installing.value) return t("安装完成后 Sunday 会自动重新打开。")
  // 后台下载可能比卡片活得更久：再次打开时它是“已经下好”，要能被点一下装掉，
  // 而不是继续显示一句“正在安装…”却什么也不会发生。
  if (downloaded.value) return t("安装包已下载并校验；点「立即安装」后 Sunday 会退出，装好后自动打开。")
  if (installBusy.value) return props.progressLabel || ''
  return ''
})
const cancelLabel = computed(() => (installBusy.value ? t("取消下载") : t("取消")))
const confirmLabel = computed(() => {
  if (installing.value) return t("正在安装…")
  if (downloaded.value) return t("立即安装")
  if (installBusy.value) return props.progressLabel ? t("下载中") : t("下载中…")
  if (props.state === 'failed') return t("重试")
  return t("更新")
})
// 已下载不再是“等着自动安装”的中间态：界面关掉过就由用户点「立即安装」。
const confirmDisabled = computed(() => installBusy.value || installing.value)

let context: gsap.Context | null = null
let closing = false
let previousFocus: HTMLElement | null = null
let focusFrame = 0

onMounted(() => {
  const card = cardEl.value
  if (!card) return
  // user:“确保视觉、功能和交互不退化”+(更新弹窗接管键盘焦点，安装时禁用无法执行的关闭操作)。
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  context = gsap.context(() => {
    if (shouldSkipMotion() || !props.origin) {
      enterScrim(scrimEl.value)
      enterFade(card)
      return
    }
    enterScrim(scrimEl.value)
    enterMorph(card, props.origin)
  }, card)
  focusFrame = requestAnimationFrame(() => {
    focusFrame = requestAnimationFrame(() => {
      if (!closing && card.isConnected) (card.querySelector<HTMLButtonElement>('button:not(:disabled)') || card).focus({ preventScroll: true })
    })
  })
})

onBeforeUnmount(() => {
  cancelAnimationFrame(focusFrame)
  context?.revert()
})
onUnmounted(() => { if (previousFocus?.isConnected) previousFocus.focus() })
watch([downloaded, installing], ([isDownloaded, isInstalling]) => {
  if ((isDownloaded || isInstalling) && cardEl.value?.contains(document.activeElement)) cardEl.value.focus({ preventScroll: true })
})

/** 缩回按钮那一小块，然后交还宿主（宿主据此卸载卡片）。 */
async function close(): Promise<void> {
  if (closing) return
  closing = true
  const card = cardEl.value
  const origin = props.origin
  if (card && origin && !shouldSkipMotion()) {
    leaveScrim(scrimEl.value)
    await leaveMorph(card, origin)
  }
  emit('closed')
}

/**
 * 关掉卡片（X / 遮罩 / Esc）：传输留在后台继续。
 *
 * user:“更新时可以后台下载。再次点更新键后的卡片继承进度”+(关闭只收卡片，不打断下载；
 * 重新点左侧的更新图标，看到的是同一条进度。安装一旦开始就无法中止，这时只允许看。)
 */
function requestClose(): void {
  // user:“确保视觉、功能和交互不退化”+(关闭动画期间忽略重复请求，避免重复收起)。
  if (closing) return
  // 安装开始以后不能关（关掉就看不到进度了）；已下载只是“等着装”，可以关，
  // 下次打开还会从主机那把同一个已校验的安装包接回来。
  if (installing.value) return
  void close()
}

/** 明确要求取消下载：这是唯一会停掉后台传输的入口。 */
function requestCancelDownload(): void {
  if (closing) return
  if (installBusy.value) {
    emit('cancel')
    void close()
    return
  }
  requestClose()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') requestClose()
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


  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 62%, transparent);

  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
  border: 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
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
