<template>
  <div
    class="overlay-root"
    :class="{ 'overlay-root--annotating': annotating }"
    :style="danmakuVars"
    @mousedown="onPointerDown"
    @mousemove="onPointerMove"
    @mouseup="onPointerUp"
  >
    <!-- user:“这个边框为什么没有包含整个屏幕边框？仅 bar 有边框”+(整屏也画同一圈
         2px 流光，胶囊压在上沿，和 Computer Use 覆盖层连成同一条线)。 -->
    <div class="overlay-frame hud-screen-frame" aria-hidden="true" />

    <svg class="overlay-canvas" :width="viewport.width" :height="viewport.height" aria-hidden="true">
      <g
        v-for="mark in canvasMarks"
        :key="mark.id"
        class="overlay-mark"
        :class="`overlay-mark--${mark.kind}`"
        :style="{ '--mark-color': mark.color, '--mark-width': `${mark.width}px`, opacity: lifeOpacity(mark, now) }"
      >
        <!-- 手绘箭头：杆和头都是抖动笔迹，先画杆再补头。 -->
        <template v-if="mark.kind === 'arrow'">
          <path class="overlay-arrow-line" pathLength="1" :d="roughArrowOf(mark).shaft" />
          <path class="overlay-arrow-head" pathLength="1" :d="roughArrowOf(mark).head" />
        </template>

        <path
          v-else-if="mark.kind === 'rect'"
          class="overlay-rect"
          pathLength="1"
          :d="roughRectPath(rectOf(mark), seedOf(mark))"
        />

        <path
          v-else-if="mark.kind === 'ellipse'"
          class="overlay-ellipse"
          pathLength="1"
          :d="roughEllipsePath(rectOf(mark), seedOf(mark))"
        />

        <path v-else-if="mark.kind === 'pen'" class="overlay-pen" :d="penPath(pagePoints(mark))" />

        <SvgMarkShapes
          v-else-if="mark.kind === 'svg'"
          :rect="rectOf(mark)"
          :view-box="mark.viewBox ?? [0, 0, rectOf(mark).width || 1, rectOf(mark).height || 1]"
          :shapes="mark.shapes ?? []"
          :draw="mark.draw"
          :now="now"
          :color="mark.color"
        />

        <g v-else-if="mark.kind === 'text'" :transform="`translate(${pagePoints(mark)[0][0]}, ${pagePoints(mark)[0][1]})`">
          <rect class="overlay-label-bg" :width="labelWidth(mark)" height="30" rx="9" />
          <text class="overlay-label-text" x="11" y="20">{{ mark.text }}</text>
        </g>
      </g>

      <!-- 圈选框同样是手绘笔迹，跟着鼠标实时长出来。 -->
      <path
        v-if="selectionBox"
        class="overlay-selection"
        :d="roughRectPath(selectionBox, 20260101, 1.6)"
      />
    </svg>

    <!-- 弹幕与表情包：位移和淡出交给 CSS 动画，跑在合成线程上。 -->
    <FloaterMarks
      :marks="floaterMarks"
      :overlay-height="overlay.height"
      :viewport-height-css="viewport.height"
      :viewport-width="viewport.width"
      :to-page="toPage"
      :settings="danmaku"
      :asset-url="assetUrl"
    />

    <!-- 工具条是覆盖层唯一吃鼠标的地方；其余位置全部穿透。
         user:“那个『收起』也去掉”+(只留清空；没有标记时整条不渲染，
         桌面上不留一条空药丸)。 -->
    <div
      v-if="marks.length"
      ref="barRef"
      class="overlay-bar hud-pill hud-pill-flow"
      data-overlay-hit
    >
      <span class="hud-pill__ring" aria-hidden="true" />
      <span class="hud-pill__text">Sunday 标注中</span>
      <button
        type="button"
        class="overlay-action hud-pill__btn hud-pill__btn--text"
        :disabled="busy"
        @click="clearAllMarks"
      >
        清空
      </button>
    </div>

    <div v-if="!annotating && hint" class="overlay-hint" aria-hidden="true">{{ hint }}</div>
  </div>
</template>

<script setup lang="ts">
/**
 * 交互层表面。
 *
 * user:“AI 直接在屏幕上标记、绘制、互动”“层改名作交互层”
 * “让它们流畅一些，箭头和圈选更像手绘风格和手绘出现”+
 * (标记内容与批注投递来自 Core；SVG 标记逐帧画，弹幕和表情包交给 CSS 动画，
 *  互不影响；默认整屏穿透，只有工具条和圈选态吃鼠标。)
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
// user:“上方那个条和电脑使用时候的样式用同一个”+(和 Computer Use 共用一份胶囊外观)。
import '@/styles/hud-pill.css'
import { useOverlayTheme } from '@/pet/ui/overlayTheme.ts'
import * as bridge from './bridge.ts'
import FloaterMarks from './FloaterMarks.vue'
import SvgMarkShapes from './SvgMarkShapes.vue'
import { lifeOpacity, DEFAULT_DANMAKU_SETTINGS, type DanmakuSettings } from './motion.ts'
import { hashSeed, roughArrow, roughEllipsePath, roughRectPath, type RoughRect } from './rough.ts'
import {
  arrowGeometry,
  penPath,
  rectFromPoints,
  resolveMark,
  toPagePoint,
  toScreenRect,
  visibleMarks,
  type OverlayMark,
  type ScreenWindow,
} from './model.ts'

useOverlayTheme()

const STATE_POLL_MS = 400
const WINDOW_POLL_MS = 500
const HEARTBEAT_MS = 2_000
/** 圈选态最多占用鼠标这么久，防止页面异常时整屏一直被吃掉。 */
const ANNOTATE_HOLD_MS = 30_000

const overlay = reactive({ x: 0, y: 0, width: 0, height: 0, scale: 1 })
const viewport = reactive({ width: window.innerWidth, height: window.innerHeight })
const marks = ref<OverlayMark[]>([])
const windows = ref<ScreenWindow[]>([])
const now = ref(Date.now() / 1000)
const danmaku = ref<DanmakuSettings>({ ...DEFAULT_DANMAKU_SETTINGS })

/** 每帧只影响需要逐帧计算的 SVG 标记，浮层不依赖 now，不会被 60fps 拖着重排。 */
const renderMarks = computed(() =>
  visibleMarks(marks.value, now.value).map(mark => resolveMark(mark, windows.value)),
)
const canvasMarks = computed(() =>
  renderMarks.value.filter(mark => mark.kind !== 'danmaku' && mark.kind !== 'sticker'),
)
/** 浮层只依赖标记和窗口，不依赖时间：CSS 动画自己跑。 */
const floaterMarks = computed(() =>
  marks.value
    .filter(mark => mark.kind === 'danmaku' || mark.kind === 'sticker')
    .map(mark => resolveMark(mark, windows.value)),
)

const danmakuVars = computed<Record<string, string>>(() => ({
  '--dm-font-size': `${danmaku.value.fontSize}px`,
  '--dm-font-family': danmaku.value.fontFamily || "'Segoe UI', system-ui, sans-serif",
}))

const annotating = ref(false)
const selection = reactive<{ start: [number, number] | null; end: [number, number] | null }>({
  start: null,
  end: null,
})
const hint = ref('')
const busy = ref(false)
const barRef = ref<HTMLElement | null>(null)

let base = ''
/** 圈选热键事件的解绑函数。 */
let unlistenCapture: (() => void) | null = null
let unlistenSettings: (() => void) | null = null
let stateTimer: ReturnType<typeof setInterval> | null = null
let windowTimer: ReturnType<typeof setInterval> | null = null
let heartbeatTimer: ReturnType<typeof setInterval> | null = null
// user:“对代码进行审查，不要出错或者低级漏洞或问题”+(可点区域定时上报的句柄
// 没存下来，页面销毁后它还在跑，白白占着已经不存在的窗口)。
let rectsTimer: ReturnType<typeof setInterval> | null = null
let annotateTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false

const selectionBox = computed<RoughRect | null>(() => {
  if (!selection.start || !selection.end) return null
  const rect = rectFromPoints([selection.start, selection.end])
  return rect
})

function assetUrl(asset: string): string {
  return base ? `${base}/api/core/overlay/assets/${asset}` : ''
}

function pagePoints(mark: OverlayMark): [number, number][] {
  return mark.points.map(point => toPagePoint(point, overlay, viewport))
}

function rectOf(mark: OverlayMark): RoughRect {
  return rectFromPoints(pagePoints(mark))
}

/** 同一个标记每次重画用同一个种子：笔迹不会闪烁。 */
function seedOf(mark: OverlayMark): number {
  return hashSeed(mark.id)
}

/**
 * 手绘箭头路径缓存：每帧都会重算标记列表，箭头路径字符串不缓存会一直重建。
 * 键带上换算后的端点，窗口移动时自动失效。
 */
const arrowCache = new Map<string, { shaft: string; head: string }>()

function roughArrowOf(mark: OverlayMark): { shaft: string; head: string } {
  const points = pagePoints(mark)
  const key = `${mark.id}:${points.map(point => `${point[0].toFixed(0)},${point[1].toFixed(0)}`).join(';')}:${mark.width}`
  const hit = arrowCache.get(key)
  if (hit) return hit
  const headSize = Math.max(14, Math.min(38, arrowGeometry(mark.points, mark.width).length * 0.15 + mark.width * 3))
  const path = roughArrow(points, seedOf(mark), headSize, 1.5)
  // 缓存只留最近的一批，跑一整天也不会无限增长。
  if (arrowCache.size > 240) arrowCache.clear()
  arrowCache.set(key, path)
  return path
}

/** 物理像素 → 页面 CSS 像素。 */
function toPage(point: [number, number]): [number, number] {
  return toPagePoint(point, overlay, viewport)
}

function labelWidth(mark: OverlayMark): number {
  return Math.max(48, mark.text.length * 14 + 22)
}

// ---------------------------------------------------------------------------
// 轮询：状态、窗口几何、弹幕设置
// ---------------------------------------------------------------------------

let rafId = 0
function tick(): void {
  now.value = Date.now() / 1000
  rafId = requestAnimationFrame(tick)
}

async function pollState(): Promise<void> {
  if (disposed) return
  now.value = Date.now() / 1000
  try {
    const state = await bridge.fetchState(base)
    marks.value = state.marks
    // user:“对外开放API，可外部调用批注功能”+(外部程序让圈选时，页面轮询到就进框选)。
    if (state.capture_requested && !annotating.value) {
      startAnnotate()
      void bridge.clearCaptureRequest(base).catch(() => undefined)
    }
  } catch {
    // Core 还没起来或正在重启：保持当前画面，等下一轮。
  }
}

async function pollWindows(): Promise<void> {
  if (disposed) return
  try {
    const list = await bridge.screenWindows()
    windows.value = list.map(item => ({
      id: String(item.id),
      title: item.title,
      bounds: item.bounds,
      z: item.z,
    }))
  } catch {
    // 拿不到窗口几何就继续用创建时的屏幕坐标，标记不会消失。
  }
}

async function loadSettings(): Promise<void> {
  try {
    const settings = await bridge.fetchSettings()
    danmaku.value = {
      speed: settings.danmaku_speed,
      fontFamily: settings.danmaku_font,
      fontSize: settings.danmaku_size,
    }
  } catch {
    // 设置拿不到就用默认值，弹幕照样能跑。
  }
}

// ---------------------------------------------------------------------------
// 命中矩形：工具条可点，圈选态整屏吃鼠标
// ---------------------------------------------------------------------------

async function reportInteractiveRects(): Promise<void> {
  if (disposed || overlay.width <= 0 || viewport.width <= 0) return
  if (annotating.value) {
    await bridge
      .setInteractiveRects([[overlay.x, overlay.y, overlay.width, overlay.height]])
      .catch(() => undefined)
    return
  }
  const ratioX = overlay.width / viewport.width
  const ratioY = overlay.height / viewport.height
  const rects: number[][] = []
  for (const element of document.querySelectorAll<HTMLElement>('[data-overlay-hit]')) {
    const box = element.getBoundingClientRect()
    if (box.width < 4 || box.height < 4) continue
    rects.push([
      Math.round(overlay.x + box.left * ratioX),
      Math.round(overlay.y + box.top * ratioY),
      Math.round(box.width * ratioX),
      Math.round(box.height * ratioY),
    ])
  }
  await bridge.setInteractiveRects(rects).catch(() => undefined)
}

watch(annotating, async () => {
  await nextTick()
  await reportInteractiveRects()
})

// ---------------------------------------------------------------------------
// 圈选与批注
// ---------------------------------------------------------------------------

/**
 * 进框选态。热键入：“圈选”只可能是开始。
 *
 * user:“没必要搞那个圈选批注的键，就是把它的入口设成跟 ping 一样就行”+
 * (工具条不再常驻圈选按钮，热键在任意位置按下都直接进框选。)
 */
function startAnnotate(): void {
  if (annotating.value) return
  annotating.value = true
  cancelSelection()
  hint.value = '按住鼠标拖一块区域，松手后进截图编辑'
  if (annotateTimer) clearTimeout(annotateTimer)
  annotateTimer = setTimeout(() => stopAnnotate(), ANNOTATE_HOLD_MS)
}

function stopAnnotate(): void {
  annotating.value = false
  cancelSelection()
  hint.value = ''
  if (annotateTimer) {
    clearTimeout(annotateTimer)
    annotateTimer = null
  }
}

function cancelSelection(): void {
  selection.start = null
  selection.end = null
}

function onPointerDown(event: MouseEvent): void {
  if (!annotating.value) return
  if ((event.target as HTMLElement | null)?.closest('[data-overlay-hit]')) return
  selection.start = [event.clientX, event.clientY]
  selection.end = [event.clientX, event.clientY]
}

function onPointerMove(event: MouseEvent): void {
  if (!selection.start) return
  selection.end = [event.clientX, event.clientY]
}

function onPointerUp(): void {
  if (!selection.start || !selection.end) return
  const rect = toScreenRect(selection.start, selection.end, overlay, viewport)
  stopAnnotate()
  if (rect[2] < 8 || rect[3] < 8) return
  // user:“合并，这样更干净”+(圈选直接进 Ping 的截图编辑器，不再自己收输入)。
  hint.value = ''
  void bridge.openCaptureRegion(rect).catch(caught => {
    hint.value = caught instanceof Error ? caught.message : String(caught)
  })
}

async function clearAllMarks(): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    await bridge.clearMarks(base, true)
    marks.value = []
  } catch {
    // 清空失败就等下一轮轮询覆盖真实状态。
  } finally {
    busy.value = false
  }
  await reportInteractiveRects()
}

function onResize(): void {
  viewport.width = window.innerWidth
  viewport.height = window.innerHeight
  void reportInteractiveRects()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  void (async () => {
    try {
      base = await bridge.apiBase()
    } catch {
      base = ''
    }
    try {
      const bounds = await bridge.overlayBounds()
      Object.assign(overlay, bounds)
    } catch (caught) {
      hint.value = caught instanceof Error ? caught.message : String(caught)
    }
    await Promise.all([pollState(), pollWindows(), loadSettings()])
    void bridge.overlayReady().catch(() => undefined)
    await reportInteractiveRects()
    // 热键可能在页面挂好之前就按下了：先取一次挂起的请求。
    try {
      if (await bridge.takeCaptureRequest()) startAnnotate()
      unlistenCapture = await bridge.onCaptureRequest(() => startAnnotate())
      unlistenSettings = await bridge.onSettingsChanged(() => void loadSettings())
    } catch {
      // 事件通道不可用不影响标记显示。
    }
    if (disposed) return
    tick()
    stateTimer = setInterval(() => void pollState(), STATE_POLL_MS)
    windowTimer = setInterval(() => void pollWindows(), WINDOW_POLL_MS)
    heartbeatTimer = setInterval(() => void bridge.heartbeat().catch(() => undefined), HEARTBEAT_MS)
    // 命中矩形会随工具条出现/消失变化，低频兜底重报一次。
    rectsTimer = setInterval(() => void reportInteractiveRects(), 1_500)
  })()
})

onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('resize', onResize)
  if (rafId) cancelAnimationFrame(rafId)
  if (stateTimer) clearInterval(stateTimer)
  if (windowTimer) clearInterval(windowTimer)
  if (heartbeatTimer) clearInterval(heartbeatTimer)
  if (rectsTimer) clearInterval(rectsTimer)
  if (annotateTimer) clearTimeout(annotateTimer)
  unlistenCapture?.()
  unlistenCapture = null
  unlistenSettings?.()
  unlistenSettings = null
})
</script>

<style scoped>
.overlay-root {
  position: fixed;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  user-select: none;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.overlay-root--annotating {
  cursor: crosshair;
  /* 圈选态整屏吃鼠标：根元素必须接收指针事件。 */
  pointer-events: auto;
}

.overlay-canvas {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

/* 整屏流光边框在 styles/hud-pill.css，压在标记下面、工具条下面。 */
.overlay-frame {
  position: fixed;
  inset: 0;
  z-index: 1;
}

/* 标记默认不接收鼠标：整层靠命中矩形决定穿透。 */
.overlay-mark {
  pointer-events: none;
}

/* 手绘笔迹：靠 pathLength=1 + dashoffset 从 0 长到满，像被一点点画出来。 */
.overlay-arrow-line,
.overlay-arrow-head,
.overlay-rect,
.overlay-ellipse,
.overlay-selection {
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 1;
  animation: overlay-draw-in 0.55s ease-out both;
}

.overlay-arrow-line {
  fill: none;
  stroke: var(--mark-color);
  stroke-width: var(--mark-width);
  filter: drop-shadow(0 1px 4px rgba(0, 0, 0, 0.45));
}

.overlay-arrow-head {
  fill: none;
  stroke: var(--mark-color);
  stroke-width: var(--mark-width);
  animation-delay: 0.35s;
  filter: drop-shadow(0 1px 4px rgba(0, 0, 0, 0.45));
}

.overlay-rect {
  fill: color-mix(in srgb, var(--mark-color) 8%, transparent);
  stroke: var(--mark-color);
  stroke-width: var(--mark-width);
  filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.35));
}

.overlay-ellipse {
  fill: color-mix(in srgb, var(--mark-color) 12%, transparent);
  stroke: var(--mark-color);
  stroke-width: var(--mark-width);
}

.overlay-pen {
  fill: none;
  stroke: var(--mark-color);
  stroke-width: var(--mark-width);
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: drop-shadow(0 1px 4px rgba(0, 0, 0, 0.45));
}

.overlay-label-bg {
  fill: rgba(16, 16, 20, 0.9);
  stroke: color-mix(in srgb, var(--mark-color) 65%, transparent);
  stroke-width: 1.5;
  filter: drop-shadow(0 4px 14px rgba(0, 0, 0, 0.45));
}

.overlay-label-text {
  fill: #f6f6f8;
  font-size: 13.5px;
  letter-spacing: 0.2px;
}

.overlay-selection {
  fill: rgba(120, 170, 255, 0.1);
  stroke: #7aa8ff;
  stroke-width: 1.6;
  animation: none;
}

/* user:“上方那个条和电脑使用时候的样式用同一个”+(只在这里定位，外观全在
   styles/hud-pill.css：贴屏幕上沿、黑底、2px 暗彩流光边，两边共用一份)。 */
.overlay-bar {
  position: fixed;
  left: 50%;
  top: 0;
  transform: translateX(-50%);
  z-index: 2;
}

/* 按钮外观同样来自 hud-pill__btn，这里不再重复定义。 */

@keyframes overlay-draw-in {
  from {
    stroke-dashoffset: 1;
  }
  to {
    stroke-dashoffset: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .overlay-arrow-line,
  .overlay-arrow-head,
  .overlay-rect,
  .overlay-ellipse {
    animation: none;
  }
}
</style>
