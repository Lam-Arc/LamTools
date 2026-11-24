<template>
  <!-- user:“除了Office类，别的都把它修好”+
       (PDF 不再塞进沙箱 iframe 指望浏览器内置查看器：那套插件在 WebView 里既可能不渲染，
        也拿不到错误。这里用 pdfjs 画到画布上，翻页、缩放、失败都能自己说清)。 -->
  <div class="preview-pdf" data-preview-pdf>
    <div class="preview-pdf__stage">
      <div v-if="!ready && !failure" class="preview-pdf__status" role="status">
        <span class="preview-pdf__spinner" aria-hidden="true" />
        <span>正在载入 PDF…</span>
      </div>
      <p v-if="failure" class="preview-pdf__error" role="alert">
        <span>{{ failure }}</span>
        <button type="button" @click="reload">重试</button>
      </p>
      <canvas v-show="ready" ref="canvasEl" class="preview-pdf__canvas" />
    </div>

    <div v-if="ready" class="preview-pdf__bar" role="toolbar" aria-label="PDF 翻页与缩放">
      <button type="button" aria-label="上一页" :disabled="page <= 1 || busy" @click="step(-1)">‹</button>
      <span class="preview-pdf__pages">{{ page }} / {{ pages || '…' }}</span>
      <button type="button" aria-label="下一页" :disabled="page >= pages || busy" @click="step(1)">›</button>
      <span class="preview-pdf__sep" aria-hidden="true" />
      <button type="button" aria-label="缩小" @click="zoomBy(-25)">−</button>
      <span class="preview-pdf__zoom">{{ zoom }}%</span>
      <button type="button" aria-label="放大" @click="zoomBy(25)">＋</button>
      <button type="button" aria-label="适应宽度" @click="fit">适应</button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 灯箱里的 PDF 查看器。
 *
 * user:“除了Office类，别的都把它修好”+(PDF 是「本机能看」的一类，不能因为浏览器内置查看器
 * 在沙箱/WebView 里不渲染就放弃；改成 pdfjs 画布渲染，和分屏里的 PDF 同一份依赖)。
 */
import { nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { PDFJS_ASSET_OPTIONS } from './pdfjsAssets'

const props = withDefaults(defineProps<{
  /** 读取原始字节：字节从预览通道来，和 markdown/office 走同一条路。 */
  loadBytes?: (() => Promise<Uint8Array>) | null
  title?: string
  loadTimeoutMs?: number
}>(), {
  loadBytes: null,
  title: '',
  loadTimeoutMs: 30000,
})

interface PdfDocumentLike {
  numPages: number
  getPage: (index: number) => Promise<any>
}

/** 加载任务：pdfjs 6 用它在卸载时释放 worker 与传输（文档对象本身没有 destroy）。 */
interface PdfLoadingTaskLike {
  promise: Promise<unknown>
  destroy: () => Promise<void>
}

const canvasEl = ref<HTMLCanvasElement | null>(null)
// user:“Cannot read private member #pagesNumber”+(pdfjs 6 的文档对象带私有字段，
// 一旦被 Vue 的深层响应式代理包住，方法里的 this 就取不到私有字段；必须 shallowRef)。
const document_ = shallowRef<PdfDocumentLike | null>(null)
let loadingTask: PdfLoadingTaskLike | null = null
const pages = ref(0)
const page = ref(1)
const zoom = ref(100)
const ready = ref(false)
const busy = ref(false)
const failure = ref('')
let task: { cancel: () => void; promise: Promise<unknown> } | null = null
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined

const fitZoom = ref(100)

function clearTimer(): void {
  if (timer !== undefined) { clearTimeout(timer); timer = undefined }
}

/**
 * pdfjs 6 内部会调用 `Uint8Array.prototype.toHex` 等新方法（ES2025）。
 * 老一点的安卓 WebView 没有这些内置方法，会在 PDF 一打开就抛 `a.toHex is not a function`。
 * 这里只补缺失的那几个，已有内置实现的浏览器不受影响。
 */
function ensureByteHelpers(): void {
  const proto = Uint8Array.prototype as Uint8Array & {
    toHex?: () => string
    toBase64?: () => string
  }
  if (typeof proto.toHex !== 'function') {
    Object.defineProperty(proto, 'toHex', {
      configurable: true,
      writable: true,
      value(this: Uint8Array) {
        let out = ''
        for (const byte of this) out += byte.toString(16).padStart(2, '0')
        return out
      },
    })
  }
  if (typeof proto.toBase64 !== 'function') {
    Object.defineProperty(proto, 'toBase64', {
      configurable: true,
      writable: true,
      value(this: Uint8Array) {
        let binary = ''
        for (const byte of this) binary += String.fromCharCode(byte)
        return btoa(binary)
      },
    })
  }
}

function armTimer(): void {
  clearTimer()
  if (!Number.isFinite(props.loadTimeoutMs) || props.loadTimeoutMs <= 0) return
  timer = setTimeout(() => {
    timer = undefined
    if (!ready.value) failure.value = 'PDF 在预期时间内没有载入，可能是文件不存在或已损坏'
  }, props.loadTimeoutMs)
}

async function load(): Promise<void> {
  const run = ++generation
  ready.value = false
  failure.value = ''
  pages.value = 0
  page.value = 1
  zoom.value = 100
  task?.cancel()
  task = null
  void loadingTask?.destroy().catch(() => undefined)
  loadingTask = null
  document_.value = null
  armTimer()
  try {
    const load = props.loadBytes
    if (!load) throw new Error('这份 PDF 没有可读取的通道')
    const bytes = await load()
    if (run !== generation) return
    // user:“PDF 预览报 a.toHex is not a function”+(pdfjs 6 用了 Uint8Array 的新内置方法，
    // 安卓 WebView 的 Chromium 版本还没有它们；这里补一层等价实现，缺什么补什么)。
    ensureByteHelpers()
    const pdfjs = await import('pdfjs-dist')
    const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default
    const started = pdfjs.getDocument({ data: bytes.slice(), ...PDFJS_ASSET_OPTIONS }) as unknown as PdfLoadingTaskLike
    loadingTask = started
    const loaded = await started.promise
    if (run !== generation) { void started.destroy().catch(() => undefined); return }
    const document = loaded as unknown as PdfDocumentLike
    document_.value = document
    pages.value = document.numPages
    ready.value = true
    clearTimer()
    await nextTick()
    if (run !== generation) return
    await paint(true)
  } catch (cause) {
    if (run !== generation) return
    clearTimer()
    ready.value = false
    failure.value = cause instanceof Error ? cause.message : 'PDF 无法打开'
  }
}

/** 把当前页画到画布；首帧按容器宽度定「适应」档，之后按 zoom 缩放。 */
async function paint(resetFit = false): Promise<void> {
  const document = document_.value
  const canvas = canvasEl.value
  if (!document || !canvas) return
  task?.cancel()
  task = null
  busy.value = true
  let current: { cancel: () => void; promise: Promise<unknown> } | null = null
  try {
    const resolved = await document.getPage(page.value)
    const hostWidth = canvas.parentElement?.clientWidth || 900
    const base = resolved.getViewport({ scale: 1 })
    if (resetFit || !fitZoom.value) fitZoom.value = Math.max(10, Math.round(((hostWidth - 32) / base.width) * 100))
    const viewport = resolved.getViewport({ scale: (fitZoom.value / 100) * (zoom.value / 100) })
    const ratio = window.devicePixelRatio || 1
    canvas.width = Math.max(1, Math.floor(viewport.width * ratio))
    canvas.height = Math.max(1, Math.floor(viewport.height * ratio))
    canvas.style.width = `${Math.floor(viewport.width)}px`
    canvas.style.height = `${Math.floor(viewport.height)}px`
    const renderTask = resolved.render({ canvas, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] })
    current = renderTask
    task = renderTask
    await renderTask.promise
    failure.value = ''
  } catch (cause) {
    if ((cause as { name?: string })?.name !== 'RenderingCancelledException') {
      failure.value = cause instanceof Error ? cause.message : 'PDF 页面渲染失败'
    }
  } finally {
    if (task === current) task = null
    busy.value = false
  }
}

function step(delta: number): void {
  const next = Math.min(pages.value || 1, Math.max(1, page.value + delta))
  if (next === page.value) return
  page.value = next
  void paint()
}

function zoomBy(delta: number): void {
  zoom.value = Math.min(400, Math.max(25, zoom.value + delta))
  void paint()
}

function fit(): void {
  zoom.value = 100
  void paint(true)
}

/** 供宿主「重新读取」用。 */
function reload(): void {
  void load()
}

watch(() => props.loadBytes, () => { void load() }, { immediate: true })
onBeforeUnmount(() => {
  generation += 1
  clearTimer()
  task?.cancel()
  void loadingTask?.destroy().catch(() => undefined)
  loadingTask = null
  document_.value = null
})

defineExpose({ reload })
</script>

<style scoped>
.preview-pdf {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--theme-main-sunken-background);
  color: var(--theme-main-text);
}

.preview-pdf__stage {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  align-items: flex-start;
  justify-content: center;
  min-height: 0;
  padding: var(--space-3);
  overflow: auto;
}

.preview-pdf__canvas {
  display: block;
  border-radius: var(--radius-sm);
  background: #fff;
  box-shadow: var(--shadow-sm);
}

.preview-pdf__status {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  font-size: 12px;
  pointer-events: none;
}

.preview-pdf__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid color-mix(in srgb, var(--theme-main-text) 24%, transparent);
  border-top-color: color-mix(in srgb, var(--theme-main-text) 68%, transparent);
  border-radius: 50%;
  animation: preview-pdf-spin 900ms linear infinite;
}

@keyframes preview-pdf-spin {
  to { transform: rotate(360deg); }
}

.preview-pdf__error {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-4);
  color: color-mix(in srgb, var(--theme-main-text) 78%, transparent);
  font-size: 12px;
  text-align: center;
}

.preview-pdf__error button {
  height: 26px;
  border: 0;
  border-radius: 999px;
  padding: 0 var(--space-3);
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.preview-pdf__bar {
  position: absolute;
  left: 50%;
  bottom: var(--space-3);
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-background) 92%, transparent);
  -webkit-backdrop-filter: blur(14px) saturate(1.1);
  backdrop-filter: blur(14px) saturate(1.1);
  box-shadow: var(--shadow-sm);
  transform: translateX(-50%);
}

.preview-pdf__bar button {
  flex: none;
  height: 28px;
  min-width: 28px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 68%, transparent);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.preview-pdf__bar button:hover:enabled {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

.preview-pdf__bar button:disabled {
  opacity: 0.45;
  cursor: default;
}

.preview-pdf__pages,
.preview-pdf__zoom {
  min-width: 44px;
  text-align: center;
  color: color-mix(in srgb, var(--theme-main-text) 70%, transparent);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.preview-pdf__sep {
  width: 1px;
  height: 16px;
  margin: 0 4px;
  background: color-mix(in srgb, var(--theme-main-text) 16%, transparent);
}

@media (prefers-reduced-motion: reduce) {
  .preview-pdf__spinner { animation-duration: 0ms; }
}
</style>
