<script setup lang="ts">
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(工作表切换复用标签键盘导航)。
import { onTabGroupKeydown } from '@/composables/radioGroupKeyboard.ts'
import { computed, inject, nextTick, onBeforeUnmount, onMounted, provide, ref, shallowRef, watch } from 'vue'
import { Copy, ExternalLink, FileQuestion, Highlighter, Maximize2, Minus, MonitorSmartphone, PanelLeftClose, PanelLeftOpen, Pencil, Plus, Quote, RefreshCw, RotateCcw, Search, X } from 'lucide-vue-next'
import MarkdownRenderer from './MarkdownRenderer.vue'
import { baseName, isTextPath, previewKindFor } from '@/split/preview'
import type { SplitTab } from '@/workspace/types'
import type { WorkspaceController } from '@/workspace/types'
import type { LamToolsTransport } from '@/transport'
import { createPreviewTransport } from '@/preview/transport'
import PreviewImageViewer from '@/preview/PreviewImageViewer.vue'
import SendToDeviceMenu from '@/components/SendToDeviceMenu.vue'
import { PREVIEW_COMPOSER_KEY } from '@/preview/composerBridge'
import {
  lengthCqw,
  parsePptxLayout,
  type PptxDeck,
  type PptxParagraph,
  type PptxShape,
  type PptxTextBody,
  type PptxTextRun,
} from '@/preview/pptxLayout'
import { copyImageBlob } from '@/preview/imageClipboard'
import { filePreviewTarget } from '@/preview/target'
import { openInLightbox, previewLightboxAvailable } from '@/preview/usePreviewLightbox'
import { PDFJS_ASSET_OPTIONS } from '@/preview/pdfjsAssets'
import { previewRasterPath, previewReadPath, resolvePreviewDocument, type PreviewDocument } from '@/preview/resolve'
import type { PreviewResolveTransport } from '@/preview/resolve'
import type { PreviewTarget } from '@/preview/target'
import { backendOriginUrl } from '@/plugins/assets'
// user:“分屏预览器不支持图片吗？改一下图片，视频 office，什么东西都尽可能支持一下”+
// (分屏预览器按文件类型渲染：图片、音视频、PDF、Word、Excel、PPT 各有对应查看方式)。
// user:“Markdown 文件也用右边那个展示”+(Markdown 用排版预览，不再只显示源码)。
// user:“预览的三态解析只有一份…不允许再出现「两套按扩展名分派」”+
// (走哪条路不再由本组件按扩展名决定：`previewKindFor` 与 `resolvePreviewDocument`
// 都从 `@/preview/route` 那唯一一张表取值，看不了时的原因与灯箱是同一句话)。
const props = defineProps<{
  tab: SplitTab
  root: string
  pane?: string
  controller?: WorkspaceController
  transport?: LamToolsTransport
  /** 解析方式默认走真实链路；展厅与测试可以注入本地示例（与灯箱同一个口子）。 */
  resolver?: ((target: PreviewTarget, transport: PreviewResolveTransport) => Promise<PreviewDocument>) | null
}>()
// Markdown 正文里的相对链接按这块预览绑定的项目解析，而不是当前主区项目。
provide('lamtools-reference-root', () => props.root)
const MAX_PREVIEW_BYTES = 256 * 1024 * 1024
/** 演示文稿的版式模型：位置、字号、颜色、图片、表格都从文件里读出来，前端自己画。 */
const deck = ref<PptxDeck | null>(null)
const MAX_MARKDOWN_BYTES = 4 * 1024 * 1024
const MAX_SHEET_ROWS = 500, MAX_SHEET_COLUMNS = 60
// 看不了的二进制（zip/tif/mkv 等）kind 为 null：它们由解析层给出原因，不该按文本读。
const kind = computed(() => previewKindFor(props.tab.resource) ?? (isTextPath(props.tab.resource) ? 'text' : null))
const name = computed(() => baseName(props.tab.resource))
const kindLabel = computed(() => ({ image: '图片', video: '视频', audio: '音频', pdf: 'PDF', docx: 'Word 文档', xlsx: '表格', pptx: '演示文稿', markdown: 'Markdown', text: '文本' } as Record<string, string>)[kind.value || ''] || '文件')
const loading = ref(false), error = ref(''), notice = ref('')
/**
 * user:“分屏预览的能力应该要比灯箱更多，即灯箱有的，分屏也该有”+
 * (输入框通道在应用层；分屏把自己看到的文件交给它，和灯箱的「引用」是同一个动作。)
 */
const composer = inject(PREVIEW_COMPOSER_KEY, null)
/** 图片走共用查看器：缩放、拖动、双击、标注都在它里面，分屏只需要给地址与原始字节。 */
const imageViewer = ref<{ hasAnnotations?: () => boolean; exportBlob?: () => Promise<Blob> } | null>(null)
const annotating = ref(false), annotationCount = ref(0), busy = ref(false)
/** user:“灯箱有的，分屏也该有”+(“发送到设备”在灯箱里是文件动作，分屏同样要有)。 */
const sendOpen = ref(false)
/** 分屏独有：文档大纲、文档内查找、选中引用。 */
const rootEl = ref<HTMLElement | null>(null)
const mainEl = ref<HTMLElement | null>(null)
const markdownHost = ref<HTMLElement | null>(null)
const slidesHost = ref<HTMLElement | null>(null)
const outline = ref<{ key: string; label: string; level: number }[]>([])
/**
 * user:“目录这种东西还是设成可折叠吧”+
 * (大纲占着左侧一条，读正文时很挡地方；折叠状态存在本机，下次打开还是上次的样子)。
 */
const OUTLINE_STORAGE_KEY = 'lamtools:split-preview-outline-open'
const outlineOpen = ref(readOutlinePreference())

function readOutlinePreference(): boolean {
  try { return localStorage.getItem(OUTLINE_STORAGE_KEY) !== "off" } catch { return true }
}
function toggleOutline(): void {
  outlineOpen.value = !outlineOpen.value
  try { localStorage.setItem(OUTLINE_STORAGE_KEY, outlineOpen.value ? "on" : "off") } catch { /* 存不住也只影响下次默认值 */ }
}
let outlineJumps: Array<() => void> = []
const findOpen = ref(false), findQuery = ref(''), findTotal = ref(0), findIndex = ref(0)
const findInput = ref<HTMLInputElement | null>(null)
let findMarks: HTMLElement[] = []
/** MarkdownRenderer 自己异步渲染：用观察器等正文真正落地后再取标题。 */
let outlineObserver: MutationObserver | null = null
let outlineTimer: ReturnType<typeof setTimeout> | undefined
const quote = ref<{ text: string; left: number; top: number } | null>(null)
const markdownText = ref('')
const textPreviewText = ref('')
/** 统一解析层的三态结果；native 时它的 url 就是媒体直连地址。 */
const resolved = ref<PreviewDocument | null>(null)
const pdf = shallowRef<{ numPages: number; getPage: (n: number) => Promise<any> } | null>(null)
const pdfPages = ref(0), pdfPage = ref(1), pdfZoom = ref(100), pdfBusy = ref(false), canvas = ref<HTMLCanvasElement | null>(null)
const docxHost = ref<HTMLElement | null>(null)
const sheets = ref<{ name: string; rows: unknown[][] }[]>([]), activeSheet = ref('')
const slides = computed(() => deck.value?.slides || [])
let buffer: Uint8Array | null = null
let pdfTask: { cancel: () => void; promise: Promise<unknown> } | null = null
// user:“除了Office类，别的都把它修好”+(pdfjs 6 的 PDFDocumentProxy 没有 destroy；
// 卸载要销毁加载任务，否则分屏释放 PDF 时会抛错)。
let pdfLoadingTask: { destroy: () => Promise<void> } | null = null
let mounted = false, generation = 0
let docxResizeObserver: ResizeObserver | null = null

/**
 * 预览文件的解析通道：地址与字节都从这一条通道出，与灯箱同一个实现。
 *
 * user:“与灯箱共用同一条解析与呈现链路”+(不再自己拼 read-reference 查询参数)。
 */
const resolveTransport = computed(() => createPreviewTransport({ transport: props.transport, origin: backendOriginUrl() }))

/** native 三态的直连地址：图片/音视频直接用它，不再把整段字节搬进内存。 */
const mediaUrl = computed(() => resolved.value?.mode === 'native' ? resolved.value.url : '')

/** 需要自己读字节再交给渲染器的类型（PDF 画布与 Office 排版都要原始字节）。 */
const needsBytes = computed(() => kind.value === 'pdf' || kind.value === 'docx' || kind.value === 'xlsx' || kind.value === 'pptx' || kind.value === 'markdown' || kind.value === 'text')

function releaseVisual() {
  pdfZoom.value = 100; pdfPage.value = 1; pdfPages.value = 0
  pdfTask?.cancel()
  pdfTask = null
  void pdfLoadingTask?.destroy().catch(() => {})
  pdfLoadingTask = null
  pdf.value = null
  buffer = null
  sheets.value = []; activeSheet.value = ''; deck.value = null; markdownText.value = ''
  setOutline([], [])
  clearFindMarks()
  outlineObserver?.disconnect(); outlineObserver = null
  if (outlineTimer) { clearTimeout(outlineTimer); outlineTimer = undefined }
  quote.value = null
  textPreviewText.value = ''
  if (docxHost.value) docxHost.value.replaceChildren()
}

async function readBytes(run: number): Promise<Uint8Array> {
  if (!props.transport) throw new Error('分屏预览需要在桌面应用中使用')
  const bytes = await resolveTransport.value.read(previewReadPath(props.tab.resource, props.root))
  if (run !== generation) throw new Error('读取已作废')
  if (bytes.byteLength > MAX_PREVIEW_BYTES) throw new Error('文件超过 256 MB，预览已停用，请使用默认应用打开')
  return bytes
}

async function open() {
  const run = ++generation
  releaseVisual()
  resolved.value = null
  error.value = ''; notice.value = ''
  const path = props.tab.resource
  if (!path) { loading.value = false; return }
  if (!props.transport) { error.value = '分屏预览需要在桌面应用中使用'; loading.value = false; return }
  loading.value = true
  annotating.value = false
  annotationCount.value = 0
  try {
    // 唯一一次解析：这条判定同时决定「看得了/看不了」与「native 用什么地址」。
    const target = { kind: 'file' as const, path, ...(props.root ? { workRoot: props.root } : {}), ...(props.tab.projectId ? { projectId: props.tab.projectId } : {}) }
    const document_ = props.resolver
      ? await props.resolver(target, resolveTransport.value)
      // user:“除了Office类，别的都把它修好”+(分屏自己有 docx/xlsx/pptx 渲染器；
      // 不声明的话解析层会把 Office 判成“看不了”，在分屏里说“去分屏看”。)
      : await resolvePreviewDocument(target, resolveTransport.value, { localRenderers: true })
    if (run !== generation) return
    resolved.value = document_
    if (document_.mode === 'unsupported') {
      // user:“不能看的，给的原因和动作与灯箱一致”+(原因直接取解析层那一句，不另写一份)。
      loading.value = false
      return
    }
    if (needsBytes.value) buffer = await readBytes(run)
    if (run !== generation) return
    loading.value = false
    await nextTick()
    if (run !== generation) return
    await render(run)
  } catch (cause) {
    if (run === generation) { error.value = cause instanceof Error ? cause.message : String(cause); loading.value = false }
  }
}

async function render(run: number) {
  if (kind.value === 'image' || kind.value === 'video' || kind.value === 'audio') return
  if (!buffer) return
  const bytes = buffer
  if (kind.value === 'pdf') return renderPdf()
  if (kind.value === 'docx') return renderDocx()
  if (kind.value === 'xlsx') return renderSheet()
  if (kind.value === 'pptx') return renderSlides()
  if (kind.value === 'markdown') {
    if (bytes.byteLength > MAX_MARKDOWN_BYTES) throw new Error('Markdown 超过 4 MB，预览已停用，请用文本编辑器或默认应用打开')
    try { markdownText.value = new TextDecoder('utf-8', { fatal: true }).decode(bytes) }
    catch { throw new Error('文件不是 UTF-8 文本，无法按 Markdown 预览') }
    await nextTick()
    observeMarkdownOutline()
  }
  if (kind.value === 'text') {
    if (bytes.byteLength > MAX_MARKDOWN_BYTES) throw new Error('文本超过 4 MB，预览已停用，请用默认应用打开')
    textPreviewText.value = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  }
}

/** user:“Markdown 文件也用右边那个展示”+(预览旁保留“编辑”，同一文件可切回文本编辑器修改)。 */
function editInSplit() {
  if (!props.controller) return
  props.controller.add('editor', props.tab.resource, name.value, props.pane, props.tab.sessionId, props.tab.root || props.root, props.tab.projectId)
}

function arrayBuffer(): ArrayBuffer {
  const bytes = buffer || new Uint8Array()
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
}

async function renderPdf() {
  const pdfjs = await import('pdfjs-dist')
  const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default
  const started = pdfjs.getDocument({ data: buffer!.slice(), ...PDFJS_ASSET_OPTIONS })
  pdfLoadingTask = started as unknown as { destroy: () => Promise<void> }
  const document = await started.promise
  pdf.value = document as any
  pdfPages.value = document.numPages
  pdfPage.value = 1
  await nextTick()
  await paintPdf()
  buildPdfOutline()
}

async function paintPdf() {
  const document = pdf.value, element = canvas.value
  if (!document || !element) return
  // 连续翻页或缩放时先取消上一帧，避免同一块画布同时渲染两次。
  pdfTask?.cancel()
  pdfTask = null
  pdfBusy.value = true
  let task: { cancel: () => void; promise: Promise<unknown> } | null = null
  try {
    const page = await document.getPage(pdfPage.value)
    const hostWidth = element.parentElement?.clientWidth || 800
    const base = page.getViewport({ scale: 1 })
    const fit = Math.max(0.1, (hostWidth - 32) / base.width)
    const viewport = page.getViewport({ scale: fit * (pdfZoom.value / 100) })
    const ratio = window.devicePixelRatio || 1
    element.width = Math.max(1, Math.floor(viewport.width * ratio))
    element.height = Math.max(1, Math.floor(viewport.height * ratio))
    element.style.width = `${Math.floor(viewport.width)}px`
    element.style.height = `${Math.floor(viewport.height)}px`
    const renderTask = page.render({ canvas: element, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] })
    task = renderTask
    pdfTask = renderTask
    await renderTask.promise
  } catch (cause) {
    if ((cause as { name?: string })?.name !== 'RenderingCancelledException') error.value = cause instanceof Error ? cause.message : 'PDF 页面渲染失败'
  } finally {
    if (pdfTask === task) pdfTask = null
    pdfBusy.value = false
  }
}

async function renderDocx() {
  const { renderAsync } = await import('docx-preview')
  const host = docxHost.value
  if (!host) return
  host.replaceChildren()
  // user:“什么东西都尽可能支持一下”+(Word 直接在分屏里排版呈现，图片与页眉页脚都保留)。
  await renderAsync(arrayBuffer(), host, host, {
    inWrapper: true, breakPages: true, ignoreWidth: false, ignoreHeight: false, ignoreFonts: false,
    renderHeaders: true, renderFooters: true, renderFootnotes: true, renderEndnotes: true,
    useBase64URL: true, className: 'split-docx-page',
  })
  ensureDocxResizeObserver(host)
  fitDocxPages()
  await nextTick()
  buildDocxOutline()
}

/**
 * user:“把附件预览给做好”+(Word 页按固定纸张宽度渲染，窄分屏会左右各裁掉一截；
 * 按面板宽度等比缩放，拖动分屏时跟着重新适配)。
 */
function fitDocxPages(): void {
  const host = docxHost.value
  if (!host) return
  const pages = host.querySelectorAll<HTMLElement>('section.split-docx-page, section.docx')
  if (!pages.length) return
  const available = Math.max(240, host.clientWidth - 12)
  for (const page of pages) {
    page.style.zoom = ''
    const natural = page.offsetWidth || 794
    page.style.zoom = natural > available ? String(Math.max(0.35, available / natural)) : ''
  }
}

function ensureDocxResizeObserver(host: HTMLElement): void {
  if (typeof ResizeObserver === 'undefined') return
  docxResizeObserver?.disconnect()
  docxResizeObserver = new ResizeObserver(() => fitDocxPages())
  docxResizeObserver.observe(host)
}

async function renderSheet() {
  // user:“什么东西都尽可能支持一下”+(用无 Worker 的通用入口读表格，避免前台 CSP 为 blob worker 开口子)。
  const { default: readXlsxFile } = await import('read-excel-file/universal')
  const workbook = await readXlsxFile(new Blob([arrayBuffer()], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
  // user:“什么东西都尽可能支持一下”+(表格按工作表分页显示；超大表只渲染前几行几列，避免整块屏卡住)。
  sheets.value = workbook.map(({ sheet, data }) => ({ name: sheet, rows: data.slice(0, MAX_SHEET_ROWS).map(row => row.slice(0, MAX_SHEET_COLUMNS)) }))
  activeSheet.value = sheets.value[0]?.name || ''
  buildSheetOutline()
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (value instanceof Date) return value.toLocaleString()
  return String(value)
}

/**
 * user:“这要求每个客户端都要有LibreOffice吗？”+
 * (不。演示文稿的版式由前端自己解析并绘制：位置与缩放按幻灯片尺寸的百分比，
 *  字号用容器宽度单位，所以分屏拉宽拉窄、整页铺满都保持同一份比例，且不依赖本机装了什么)。
 */
async function renderSlides() {
  const { unzipSync } = await import('fflate')
  deck.value = parsePptxLayout(unzipSync(new Uint8Array(arrayBuffer())) as unknown as Record<string, Uint8Array>)
  if (!deck.value.slides.length) notice.value = '这份演示文稿没有可显示的幻灯片'
  await nextTick()
  buildSlidesOutline()
}

/** 形状：绝对定位到幻灯片的百分比坐标，旋转与填充按文件里的值。 */
function shapeStyle(shape: PptxShape): Record<string, string> {
  const width = deck.value?.width || 1
  const height = deck.value?.height || 1
  const style: Record<string, string> = {
    left: `${(shape.x / width) * 100}%`,
    top: `${(shape.y / height) * 100}%`,
    width: `${(shape.w / width) * 100}%`,
    height: `${(shape.h / height) * 100}%`,
  }
  if (shape.rotation) style.transform = `rotate(${shape.rotation}deg)`
  if (shape.gradient) style.background = shape.gradient
  else if (shape.fill) style.background = shape.fill
  if (shape.line) style.border = `${Math.max(1, shape.line.width / 12700)}px solid ${shape.line.color}`
  const radius = shape.geometry === 'ellipse' ? '50%' : shape.geometry === 'roundRect' ? '6%' : ''
  if (radius) style.borderRadius = radius
  return style
}

/** 文本框：内边距与垂直锚点按 bodyPr，换行交给浏览器。 */
function textBoxStyle(body: PptxTextBody): Record<string, string> {
  const width = deck.value?.width || 1
  const anchor = body.anchor === 'middle' ? 'center' : body.anchor === 'bottom' ? 'flex-end' : 'flex-start'
  return {
    justifyContent: anchor,
    padding: `${lengthCqw(body.inset.top / 12700, width)} ${lengthCqw(body.inset.right / 12700, width)} ${lengthCqw(body.inset.bottom / 12700, width)} ${lengthCqw(body.inset.left / 12700, width)}`,
    whiteSpace: body.wrap ? 'pre-wrap' : 'nowrap',
  }
}

/** 段落：项目符号用“左边距 + 负首行缩进”实现，和 PowerPoint 的排法一致。 */
function paragraphStyle(paragraph: PptxParagraph): Record<string, string> {
  const width = deck.value?.width || 1
  const style: Record<string, string> = {
    textAlign: paragraph.align,
    paddingLeft: lengthCqw(paragraph.marginLeft, width),
    textIndent: lengthCqw(paragraph.indent, width),
  }
  if (paragraph.size) style.fontSize = lengthCqw(paragraph.size, width)
  if (paragraph.color) style.color = paragraph.color
  if (paragraph.lineHeight) style.lineHeight = String(paragraph.lineHeight)
  if (paragraph.spaceBefore) style.marginTop = lengthCqw(paragraph.spaceBefore, width)
  if (paragraph.spaceAfter) style.marginBottom = lengthCqw(paragraph.spaceAfter, width)
  return style
}

function runStyle(run: PptxTextRun): Record<string, string> {
  const width = deck.value?.width || 1
  const style: Record<string, string> = {}
  if (run.size) style.fontSize = lengthCqw(run.size, width)
  if (run.color) style.color = run.color
  if (run.bold) style.fontWeight = '700'
  if (run.italic) style.fontStyle = 'italic'
  if (run.underline) style.textDecoration = 'underline'
  if (run.font) style.fontFamily = `'${run.font}', 'Microsoft YaHei', system-ui, sans-serif`
  return style
}
function stepPdf(delta: number) {
  const next = Math.min(pdfPages.value, Math.max(1, pdfPage.value + delta))
  if (next === pdfPage.value) return
  pdfPage.value = next
  void paintPdf()
}

function changePdfZoom(delta: number) {
  pdfZoom.value = Math.min(400, Math.max(50, pdfZoom.value + delta))
  void paintPdf()
}

function fit() {
  pdfZoom.value = 100
  void paintPdf()
}

function onKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') { event.preventDefault(); openFind(); return }
  if (event.key === 'Escape' && findOpen.value) { event.preventDefault(); closeFind(); return }
  if (event.key === 'ArrowLeft' && kind.value === 'pdf') { event.preventDefault(); stepPdf(-1); return }
  if (event.key === 'ArrowRight' && kind.value === 'pdf') { event.preventDefault(); stepPdf(1); return }
  if (event.key === '+' || event.key === '=') { event.preventDefault(); changePdfZoom(25) }
  else if (event.key === '-' || event.key === '_') { event.preventDefault(); changePdfZoom(-25) }
  else if (event.key === '0') { event.preventDefault(); fit() }
}

/** 原字节：合成标注图要用它重新解码，跨源画布不能直接导出。 */
async function loadOriginalImage(): Promise<Blob> {
  const raster = resolved.value?.mode === 'native' && resolved.value.url.includes('/files/preview-image')
  const readPath = raster ? previewRasterPath(props.tab.resource, props.root) : previewReadPath(props.tab.resource, props.root)
  const bytes = await resolveTransport.value.read(readPath)
  const buffer = bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength ? bytes.buffer : bytes.slice().buffer
  const mime = resolved.value?.mode === 'native' ? resolved.value.mime : 'image/png'
  return new Blob([buffer as ArrayBuffer], { type: mime })
}

/** 有标注就给合成图，没有就给原图（与灯箱同一套取值规则）。 */
async function imagePayload(): Promise<{ blob: Blob; filename: string }> {
  const viewer = imageViewer.value
  const base = name.value.replace(/\.[^.]+$/, '') || 'image'
  if (viewer?.hasAnnotations?.()) return { blob: await viewer.exportBlob!(), filename: `${base}-标注.png` }
  return { blob: await loadOriginalImage(), filename: name.value }
}

/**
 * user:“灯箱有的，分屏也该有”+(复制：图片给图，其它文件给路径——常驻面板里复制的
 * 多半是要把它贴到别处，路径就是这份文件最稳定的身份)。
 */
async function copyAction(): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    if (kind.value === 'image' && mediaUrl.value) {
      const { blob } = await imagePayload()
      await copyImageBlob(blob)
      notice.value = annotationCount.value ? '已复制标注图' : '已复制原图'
    } else {
      await navigator.clipboard.writeText(props.tab.resource)
      notice.value = '已复制文件路径'
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '复制失败'
  } finally { busy.value = false }
}

/** 引用：把这份文件交给输入框；标注过的图片交合成图。 */
async function referenceAction(): Promise<void> {
  const bridge = composer
  if (!bridge?.canAttach() || busy.value) return
  busy.value = true
  try {
    if (kind.value === 'image' && imageViewer.value?.hasAnnotations?.()) {
      const { blob, filename } = await imagePayload()
      await bridge.attach([new File([blob], filename, { type: blob.type || 'image/png' })])
    } else {
      await bridge.attach([{ path: props.tab.resource, name: name.value }])
    }
    notice.value = '已加入输入框'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '引用失败'
  } finally { busy.value = false }
}

/**
 * user:“分屏预览的能力应该要比灯箱更多”+(分屏是常驻的工作区：文档要能跳章节、
 * 要能在正文里找词、看到一段话要能直接递给 Agent——这三件事在“看完即关”的灯箱里没有意义)。
 */
function setOutline(items: { key: string; label: string; level: number }[], jumps: Array<() => void>) {
  outline.value = items
  outlineJumps = jumps
}
/** 滚动到目标位置：没有这个能力的环境（jsdom / 老引擎）跳过，不让一次跳转炸掉预览。 */
function scrollInto(target: Element | null | undefined, block: ScrollLogicalPosition = 'start'): void {
  const element = target as HTMLElement | null | undefined
  if (!element || typeof element.scrollIntoView !== 'function') return
  element.scrollIntoView({ block, behavior: 'smooth' })
}

function jumpToOutline(index: number) { outlineJumps[index]?.() }

function buildDocxOutline() {
  const host = docxHost.value
  if (!host) return
  const headings = [...host.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')].filter(item => (item.textContent || '').trim())
  setOutline(
    headings.map((item, index) => ({ key: `docx-${index}`, label: (item.textContent || '').trim().slice(0, 80), level: Number(item.tagName.slice(1)) })),
    headings.map(item => () => scrollInto(item)),
  )
}

function scheduleMarkdownOutline() {
  if (outlineTimer) clearTimeout(outlineTimer)
  outlineTimer = setTimeout(() => { outlineTimer = undefined; buildMarkdownOutline() }, 60)
}

function observeMarkdownOutline() {
  const host = markdownHost.value
  if (!host) return
  if (typeof MutationObserver === 'undefined') { scheduleMarkdownOutline(); return }
  outlineObserver?.disconnect()
  outlineObserver = new MutationObserver(scheduleMarkdownOutline)
  outlineObserver.observe(host, { childList: true, subtree: true })
  scheduleMarkdownOutline()
}

function buildMarkdownOutline() {
  const host = markdownHost.value
  if (!host) return
  const headings = [...host.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')].filter(item => (item.textContent || '').trim())
  setOutline(
    headings.map((item, index) => ({ key: `md-${index}`, label: (item.textContent || '').trim().slice(0, 80), level: Number(item.tagName.slice(1)) })),
    headings.map(item => () => scrollInto(item)),
  )
}

function buildSheetOutline() {
  if (sheets.value.length <= 1) { setOutline([], []); return }
  setOutline(sheets.value.map(sheet => ({ key: sheet.name, label: sheet.name, level: 1 })), sheets.value.map(sheet => () => { activeSheet.value = sheet.name }))
}

function buildSlidesOutline() {
  setOutline(slides.value.map(slide => ({ key: `slide-${slide.index}`, label: `${slide.index}. ${slide.title}`, level: 1 })), slides.value.map(slide => () => {
    const target = slidesHost.value?.querySelector<HTMLElement>(`[data-slide="${slide.index}"]`)
    scrollInto(target)
  }))
}

function buildPdfOutline() {
  const total = pdfPages.value
  if (!total) { setOutline([], []); return }
  setOutline(
    Array.from({ length: total }, (_, index) => ({ key: `page-${index + 1}`, label: `第 ${index + 1} 页`, level: 1 })),
    Array.from({ length: total }, (_, index) => () => { pdfPage.value = index + 1; void paintPdf() }),
  )
}

// ---- 文档内查找：在正文里做标记并逐个跳转（Word / Markdown / 纯文本） ----
const FINDABLE = ['text', 'markdown', 'docx']
const findable = computed(() => FINDABLE.includes(kind.value || ''))
const findScope = computed(() => (kind.value === 'docx' ? docxHost.value : mainEl.value))

function clearFindMarks() {
  for (const mark of findMarks.splice(0)) {
    const parent = mark.parentNode
    if (!parent) continue
    parent.replaceChild(document.createTextNode(mark.textContent || ''), mark)
    parent.normalize()
  }
  findTotal.value = 0
  findIndex.value = 0
}

function applyFind() {
  clearFindMarks()
  const root = findScope.value
  const query = findQuery.value.trim()
  if (!root || !query) return
  const needle = query.toLowerCase()
  const nodes: Text[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: node => (node.nodeValue || '').toLowerCase().includes(needle) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
  })
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  for (const node of nodes) {
    const value = node.nodeValue || ''
    const lower = value.toLowerCase()
    const fragment = document.createDocumentFragment()
    let cursor = 0
    let index = lower.indexOf(needle)
    while (index >= 0) {
      if (index > cursor) fragment.appendChild(document.createTextNode(value.slice(cursor, index)))
      const mark = document.createElement('mark')
      mark.className = 'split-find-hit'
      mark.textContent = value.slice(index, index + query.length)
      fragment.appendChild(mark)
      findMarks.push(mark)
      cursor = index + query.length
      index = lower.indexOf(needle, cursor)
    }
    if (cursor < value.length) fragment.appendChild(document.createTextNode(value.slice(cursor)))
    node.parentNode?.replaceChild(fragment, node)
  }
  findTotal.value = findMarks.length
  if (findMarks.length) gotoFind(0)
}

function gotoFind(index: number) {
  if (!findMarks.length) return
  const total = findMarks.length
  const next = ((index % total) + total) % total
  findIndex.value = next
  for (const [position, mark] of findMarks.entries()) mark.classList.toggle('is-active', position === next)
  scrollInto(findMarks[next], 'center')
}

function openFind() {
  if (!findable.value) return
  findOpen.value = true
  void nextTick(() => { findInput.value?.focus(); findInput.value?.select() })
}

function closeFind() {
  clearFindMarks()
  findOpen.value = false
  findQuery.value = ''
}

/** 选中正文里的一段话：在选区上方浮一个“引用”入口（灯箱做不到——它是模态的）。 */
function onSelectionEnd() {
  const selection = window.getSelection()
  const selected = selection?.toString().trim() || ''
  const node = selection?.anchorNode
  if (!selection || !selected || !node || !mainEl.value?.contains(node)) { quote.value = null; return }
  const range = selection.getRangeAt(0)
  const rect = typeof range.getBoundingClientRect === 'function' ? range.getBoundingClientRect() : ({ left: 0, top: 0, width: 0 } as DOMRect)
  const host = rootEl.value?.getBoundingClientRect()
  const left = Math.max(8, Math.min((host?.width || 0) - 132, rect.left - (host?.left || 0) + rect.width / 2 - 60))
  const top = Math.max(8, rect.top - (host?.top || 0) - 38)
  quote.value = { text: selected.slice(0, 4000), left, top }
}

function insertQuote() {
  const current = quote.value
  if (!current || !composer?.insert) return
  composer.insert(current.text)
  quote.value = null
  window.getSelection()?.removeAllRanges()
  notice.value = '已把选中内容加入输入框'
}
/** 灯箱能看的媒体，在分屏里也能一键丢回灯箱（看完即关的场景）。 */
const canOpenInLightbox = computed(() => previewLightboxAvailable() && ['image', 'video', 'audio', 'pdf'].includes(kind.value || ''))
function openInLightboxAction(): void {
  openInLightbox(filePreviewTarget(props.tab.resource, { workRoot: props.root }))
}
async function openWithDefaultApp() {
  if (!props.transport) return
  error.value = ''
  try {
    const response = await props.transport.request<{ status: number; body: Uint8Array }>({
      kind: 'http', method: 'POST', path: '/files/open-reference',
      headers: { 'Content-Type': 'application/json' },
      body: new TextEncoder().encode(JSON.stringify({ path: props.tab.resource, work_root: props.root })),
    })
    if (response.status < 200 || response.status >= 300) {
      let detail = '文件无法打开'
      try {
        const payload = JSON.parse(new TextDecoder().decode(response.body))
        if (typeof payload.detail === 'string') detail = payload.detail
      } catch { /* 非 JSON 失败保留可读的兜底文案。 */ }
      throw new Error(detail)
    }
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '文件无法打开' }
}

// 图片的缩放/拖动由共用查看器自己的工具坞负责，这里只留 PDF 的缩放按钮。
const canZoom = computed(() => kind.value === 'pdf')
const zoomValue = computed(() => pdfZoom.value)
const zoomReady = computed(() => pdfPages.value > 0)
function zoomBy(delta: number) { if (canZoom.value) changePdfZoom(delta) }

/** 看不了时展示解析层给出的那句原因；与灯箱完全一致。 */
const blockReason = computed(() => resolved.value?.mode === 'unsupported' ? resolved.value.reason : '')

onMounted(() => { mounted = true; void open() })
watch(() => [props.tab.resource, props.root], () => { if (mounted) void open() })
onBeforeUnmount(() => { generation++; docxResizeObserver?.disconnect(); docxResizeObserver = null; releaseVisual() })
</script>
<template>
  <div ref="rootEl" class="split-preview" tabindex="-1" @keydown="onKeydown">
    <div class="split-content-toolbar">
      <span class="split-path" :title="tab.resource">{{ name }}</span>
      <span class="split-preview-kind">{{ kindLabel }}</span>
      <template v-if="canZoom">
        <button class="split-icon-button" type="button" title="缩小" aria-label="缩小预览" :disabled="!zoomReady" @click="zoomBy(-25)"><Minus :size="14" /></button>
        <span class="split-preview-zoom" aria-live="polite">{{ zoomValue }}%</span>
        <button class="split-icon-button" type="button" title="放大" aria-label="放大预览" :disabled="!zoomReady" @click="zoomBy(25)"><Plus :size="14" /></button>
        <button class="split-icon-button" type="button" title="适应窗口 · 按 0" aria-label="适应窗口" :disabled="!zoomReady" @click="fit"><RotateCcw :size="14" /></button>
      </template>
      <button v-if="kind === 'image'" class="split-icon-button" :class="{ active: annotating }" type="button" :title="annotating ? '完成标注' : '标注'" :aria-label="annotating ? '完成标注' : '标注'" :aria-pressed="annotating" @click="annotating = !annotating"><Highlighter :size="14" /></button>
      <button class="split-icon-button" type="button" title="复制" aria-label="复制" :disabled="busy" @click="copyAction"><Copy :size="14" /></button>
      <button v-if="composer" class="split-icon-button" type="button" title="加入输入框" aria-label="加入输入框" :disabled="busy || !composer.canAttach()" @click="referenceAction"><Quote :size="14" /></button>
      <button v-if="canOpenInLightbox" class="split-icon-button" type="button" title="在灯箱中打开" aria-label="在灯箱中打开" @click="openInLightboxAction"><Maximize2 :size="14" /></button>
      <button v-if="tab.resource" class="split-icon-button" type="button" title="发送到设备" aria-label="发送到设备" :aria-expanded="sendOpen" @click="sendOpen = !sendOpen"><MonitorSmartphone :size="14" /></button>
      <button v-if="outline.length" class="split-icon-button" type="button" :title="outlineOpen ? '收起目录' : '展开目录'" :aria-label="outlineOpen ? '收起目录' : '展开目录'" :aria-expanded="outlineOpen" aria-controls="split-preview-outline" data-split-outline-toggle @click="toggleOutline"><PanelLeftClose v-if="outlineOpen" :size="14" /><PanelLeftOpen v-else :size="14" /></button>
      <button v-if="findable" class="split-icon-button" type="button" title="在文档中查找 · Ctrl+F" aria-label="在文档中查找" @click="openFind"><Search :size="14" /></button>
      <button v-if="kind === 'markdown' && controller" class="split-icon-button" type="button" title="在文本编辑器中编辑" aria-label="在文本编辑器中编辑" @click="editInSplit"><Pencil :size="14" /></button>
      <button class="split-icon-button" type="button" title="重新读取" aria-label="重新读取" @click="open"><RefreshCw :size="14" /></button>
      <button class="split-icon-button" type="button" title="使用默认应用打开" aria-label="使用默认应用打开" @click="openWithDefaultApp"><ExternalLink :size="14" /></button>
    </div>
    <div v-if="findOpen" class="split-preview-find" data-split-find>
      <Search :size="13" aria-hidden="true" />
      <input ref="findInput" v-model="findQuery" type="search" placeholder="在文档中查找" aria-label="在文档中查找" @input="applyFind" @keydown.enter.prevent="gotoFind(findIndex + (($event.shiftKey) ? -1 : 1))">
      <span class="split-preview-find-count" aria-live="polite">{{ findTotal ? `${findIndex + 1} / ${findTotal}` : "无匹配" }}</span>
      <button class="split-icon-button" type="button" aria-label="上一个匹配" :disabled="!findTotal" @click="gotoFind(findIndex - 1)">‹</button>
      <button class="split-icon-button" type="button" aria-label="下一个匹配" :disabled="!findTotal" @click="gotoFind(findIndex + 1)">›</button>
      <button class="split-icon-button" type="button" aria-label="关闭查找" @click="closeFind"><X :size="13" /></button>
    </div>
    <div class="split-preview-stage">
      <aside v-if="outline.length && outlineOpen" id="split-preview-outline" class="split-preview-outline" data-split-outline aria-label="文档大纲">
        <button v-for="(item, index) in outline" :key="item.key" type="button" class="split-preview-outline-item" :style="{ paddingLeft: `${8 + (item.level - 1) * 10}px` }" @click="jumpToOutline(index)">{{ item.label }}</button>
      </aside>
      <div ref="mainEl" class="split-preview-main" @mouseup="onSelectionEnd">
    <p v-if="error" class="split-content-error" role="alert">{{ error }}<button v-if="!loading" class="split-text-button" @click="open">重试</button></p>
    <p v-else-if="notice" class="split-content-notice">{{ notice }}</p>
    <p v-if="loading" class="split-content-notice" role="status">正在打开文件…</p>
    <div v-else-if="!tab.resource" class="split-empty"><FileQuestion :size="22" /><span>从文件树选择文件后在这里预览</span></div>
    <div v-else-if="blockReason" class="split-empty">
      <FileQuestion :size="22" />
      <span>{{ blockReason }}</span>
      <button class="split-text-button" type="button" @click="openWithDefaultApp">使用默认应用打开</button>
    </div>
    <div v-else-if="kind === 'markdown'" ref="markdownHost" class="split-preview-body split-preview-body--markdown">
      <MarkdownRenderer class="split-preview-markdown" :content="markdownText" />
    </div>
    <div v-else-if="kind === 'text'" class="split-preview-body split-preview-body--text">
      <pre class="split-preview-text">{{ textPreviewText }}</pre>
    </div>
    <div v-else-if="kind === 'image' && mediaUrl" class="split-preview-body split-preview-body--media split-preview-body--image">
      <PreviewImageViewer
        ref="imageViewer"
        :src="mediaUrl"
        :name="name"
        :annotating="annotating"
        :load-original="loadOriginalImage"
        @update:annotating="annotating = $event"
        @annotations-change="annotationCount = $event"
      />
    </div>
    <div v-else-if="kind === 'video' && mediaUrl" class="split-preview-body split-preview-body--media">
      <video :src="mediaUrl" controls preload="metadata" @error="error = '这个视频格式当前无法播放，请使用默认应用打开'">当前环境不支持视频播放</video>
    </div>
    <div v-else-if="kind === 'audio' && mediaUrl" class="split-preview-body split-preview-body--media split-preview-body--audio">
      <audio :src="mediaUrl" controls preload="metadata" @error="error = '这个音频格式当前无法播放，请使用默认应用打开'">当前环境不支持音频播放</audio>
    </div>
    <div v-else-if="kind === 'pdf'" class="split-preview-body split-preview-body--document">
      <div class="split-preview-pager">
        <button class="split-icon-button" type="button" aria-label="上一页" :disabled="pdfPage <= 1 || pdfBusy" @click="stepPdf(-1)">‹</button>
        <span>{{ pdfPage }} / {{ pdfPages || '…' }}</span>
        <button class="split-icon-button" type="button" aria-label="下一页" :disabled="pdfPage >= pdfPages || pdfBusy" @click="stepPdf(1)">›</button>
      </div>
      <canvas ref="canvas" class="split-preview-canvas" />
    </div>
    <div v-else-if="kind === 'docx'" ref="docxHost" class="split-preview-body split-preview-body--document split-preview-docx"></div>
    <div v-else-if="kind === 'xlsx'" class="split-preview-body split-preview-body--document">
      <div v-if="sheets.length > 1" class="split-preview-sheet-tabs" role="tablist" aria-label="工作表" @keydown="onTabGroupKeydown">
        <button v-for="sheet in sheets" :key="sheet.name" type="button" role="tab" :aria-selected="sheet.name === activeSheet" :tabindex="sheet.name === activeSheet ? 0 : -1" :class="{ active: sheet.name === activeSheet }" @click="activeSheet = sheet.name">{{ sheet.name }}</button>
      </div>
      <div v-for="sheet in sheets" v-show="sheet.name === activeSheet" :key="sheet.name" class="split-preview-sheet">
        <table>
          <tbody>
            <tr v-for="(row, rowIndex) in sheet.rows" :key="rowIndex">
              <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cellText(cell) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!sheets.length" class="split-content-notice">这个表格没有可显示的工作表</p>
    </div>
    <div v-else-if="kind === 'pptx'" ref="slidesHost" class="split-preview-body split-preview-body--document" data-split-slides>
      <article
        v-for="slide in slides"
        :key="slide.index"
        class="pptx-slide"
        :data-slide="slide.index"
        :style="{ aspectRatio: `${deck?.width || 4} / ${deck?.height || 3}`, background: slide.background }"
      >
        <span class="pptx-slide-number">{{ slide.index }}</span>
        <div v-for="shape in slide.shapes" :key="shape.key" class="pptx-shape" :style="shapeStyle(shape)">
          <img v-if="shape.kind === 'image' && shape.image" class="pptx-image" :src="shape.image.url" :alt="shape.name || ''" />
          <table v-else-if="shape.kind === 'table' && shape.table" class="pptx-table">
            <colgroup>
              <col
                v-for="(column, columnIndex) in shape.table.columns"
                :key="columnIndex"
                :style="{ width: `${(column / Math.max(1, shape.table.columns.reduce((sum, value) => sum + value, 0))) * 100}%` }"
              />
            </colgroup>
            <tbody>
              <tr v-for="(row, rowIndex) in shape.table.rows" :key="rowIndex">
                <td
                  v-for="(cell, cellIndex) in row.cells"
                  :key="cellIndex"
                  :colspan="cell.gridSpan"
                  :style="{ background: cell.fill || 'transparent' }"
                >
                  <div v-if="cell.text" class="pptx-text" :style="textBoxStyle(cell.text)">
                    <p v-for="(paragraph, paragraphIndex) in cell.text.paragraphs" :key="paragraphIndex" :style="paragraphStyle(paragraph)">
                      <span v-for="(run, runIndex) in paragraph.runs" :key="runIndex" :style="runStyle(run)">{{ run.text }}</span>
                    </p>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else-if="shape.text" class="pptx-text" :style="textBoxStyle(shape.text)">
            <p v-for="(paragraph, paragraphIndex) in shape.text.paragraphs" :key="paragraphIndex" :style="paragraphStyle(paragraph)">
              <span v-if="paragraph.bullet" class="pptx-bullet">{{ paragraph.bullet }}</span>
              <span v-for="(run, runIndex) in paragraph.runs" :key="runIndex" :style="runStyle(run)">{{ run.text }}</span>
            </p>
          </div>
        </div>
      </article>
      <p v-if="!slides.length" class="split-content-notice">这份演示文稿没有可显示的幻灯片</p>
    </div>
    <div v-else-if="!error && !loading" class="split-empty">
      <FileQuestion :size="22" />
      <span>这个文件暂时无法预览</span>
      <button class="split-text-button" type="button" @click="openWithDefaultApp">使用默认应用打开</button>
    </div>
      </div>
    </div>
    <div v-if="sendOpen" class="split-preview-send" data-split-send @click.stop>
      <SendToDeviceMenu :path="tab.resource" :name="name" @sent="sendOpen = false" @close="sendOpen = false" />
    </div>
    <button v-if="quote" class="split-preview-quote" type="button" :style="{ left: `${quote.left}px`, top: `${quote.top}px` }" data-split-quote @click="insertQuote">
      <Quote :size="13" aria-hidden="true" />引用给 Agent
    </button>
  </div>
</template>
