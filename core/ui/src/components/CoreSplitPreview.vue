<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, shallowRef, watch } from 'vue'
import { ExternalLink, FileQuestion, Minus, Pencil, Plus, RefreshCw, RotateCcw } from 'lucide-vue-next'
import MarkdownRenderer from './MarkdownRenderer.vue'
import { baseName, previewKindFor, type SplitPreviewKind } from '@/split/preview'
import type { SplitTab } from '@/split/layout'
import type { SplitWorkspaceController } from '@/split/useSplitWorkspace'
import type { LamToolsTransport, TransportHttpResponse } from '@/transport'
// user:“分屏预览器不支持图片吗？改一下图片，视频 office，什么东西都尽可能支持一下”+
// (分屏预览器按文件类型渲染：图片、音视频、PDF、Word、Excel、PPT 各有对应查看方式)。
// user:“Markdown 文件也用右边那个展示”+(Markdown 用排版预览，不再只显示源码)。
const props = defineProps<{ tab: SplitTab; root: string; pane?: string; controller?: SplitWorkspaceController; transport?: LamToolsTransport }>()
// Markdown 正文里的相对链接按这块预览绑定的项目解析，而不是当前主区项目。
provide('lamtools-reference-root', () => props.root)
const MAX_PREVIEW_BYTES = 256 * 1024 * 1024
const MAX_MARKDOWN_BYTES = 4 * 1024 * 1024
const MAX_SHEET_ROWS = 500, MAX_SHEET_COLUMNS = 60
const kind = computed<SplitPreviewKind | null>(() => previewKindFor(props.tab.resource))
const name = computed(() => baseName(props.tab.resource))
const kindLabel = computed(() => ({ image: '图片', video: '视频', audio: '音频', pdf: 'PDF', docx: 'Word 文档', xlsx: '表格', pptx: '演示文稿', markdown: 'Markdown' } as Record<string, string>)[kind.value || ''] || '文件')
const loading = ref(false), error = ref(''), notice = ref('')
const blobUrl = ref(''), imageZoom = ref(100), markdownText = ref('')
const pdf = shallowRef<{ numPages: number; getPage: (n: number) => Promise<any>; destroy: () => Promise<void> } | null>(null)
const pdfPages = ref(0), pdfPage = ref(1), pdfZoom = ref(100), pdfBusy = ref(false), canvas = ref<HTMLCanvasElement | null>(null)
const docxHost = ref<HTMLElement | null>(null)
const sheets = ref<{ name: string; rows: unknown[][] }[]>([]), activeSheet = ref('')
const slides = ref<{ index: number; title: string; lines: string[]; notes: string[]; images: string[] }[]>([])
const slideImageUrls: string[] = []
let buffer: Uint8Array | null = null
let pdfTask: { cancel: () => void; promise: Promise<unknown> } | null = null
let mounted = false, generation = 0

function mediaType(path: string): string {
  const ext = path.replace(/\\/g, '/').split('.').pop()?.toLowerCase() || ''
  return ({
    png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp',
    bmp: 'image/bmp', ico: 'image/x-icon', svg: 'image/svg+xml', avif: 'image/avif', tif: 'image/tiff', tiff: 'image/tiff',
    mp4: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime', m4v: 'video/mp4', ogv: 'video/ogg', mkv: 'video/x-matroska', avi: 'video/x-msvideo',
    mp3: 'audio/mpeg', wav: 'audio/wav', ogg: 'audio/ogg', oga: 'audio/ogg', m4a: 'audio/mp4', flac: 'audio/flac', aac: 'audio/aac', opus: 'audio/ogg',
  } as Record<string, string>)[ext] || 'application/octet-stream'
}

function releaseVisual() {
  if (blobUrl.value) URL.revokeObjectURL(blobUrl.value)
  blobUrl.value = ''
  imageZoom.value = 100; pdfZoom.value = 100; pdfPage.value = 1; pdfPages.value = 0
  pdfTask?.cancel()
  pdfTask = null
  void pdf.value?.destroy().catch(() => {})
  pdf.value = null
  buffer = null
  sheets.value = []; activeSheet.value = ''; slides.value = []; markdownText.value = ''
  for (const url of slideImageUrls.splice(0)) URL.revokeObjectURL(url)
  if (docxHost.value) docxHost.value.replaceChildren()
}

function detailOf(response: TransportHttpResponse, fallback: string): string {
  try {
    const payload = JSON.parse(new TextDecoder().decode(response.body))
    return typeof payload.detail === 'string' ? payload.detail : fallback
  } catch { return fallback }
}

function readPath(): string {
  const query = new URLSearchParams({ path: props.tab.resource, ...(props.root ? { work_root: props.root } : {}) })
  return `/files/read-reference?${query.toString()}`
}

async function open() {
  const run = ++generation
  releaseVisual()
  error.value = ''; notice.value = ''
  if (!props.tab.resource) { loading.value = false; return }
  if (!kind.value) { error.value = '这个文件类型暂不支持内置预览，可用右上角的按钮交给默认应用打开'; return }
  if (!props.transport) { error.value = '分屏预览需要在桌面应用中使用'; return }
  loading.value = true
  try {
    const response = await props.transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path: readPath(), timeoutMs: 120_000 })
    if (run !== generation) return
    if (response.status < 200 || response.status >= 300) throw new Error(detailOf(response, '文件无法读取'))
    if (response.body.byteLength > MAX_PREVIEW_BYTES) throw new Error('文件超过 256 MB，预览已停用，请使用默认应用打开')
    buffer = response.body
    loading.value = false
    await nextTick()
    if (run !== generation) return
    await render()
  } catch (cause) {
    if (run === generation) { error.value = cause instanceof Error ? cause.message : String(cause); loading.value = false }
  }
}

async function render() {
  if (!buffer) return
  const bytes = buffer
  if (kind.value === 'image' || kind.value === 'video' || kind.value === 'audio') {
    const copy = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
    blobUrl.value = URL.createObjectURL(new Blob([copy], { type: mediaType(props.tab.resource) }))
    return
  }
  if (kind.value === 'pdf') return renderPdf()
  if (kind.value === 'docx') return renderDocx()
  if (kind.value === 'xlsx') return renderSheet()
  if (kind.value === 'pptx') return renderSlides()
  if (kind.value === 'markdown') {
    if (bytes.byteLength > MAX_MARKDOWN_BYTES) throw new Error('Markdown 超过 4 MB，预览已停用，请用文本编辑器或默认应用打开')
    try { markdownText.value = new TextDecoder('utf-8', { fatal: true }).decode(bytes) }
    catch { throw new Error('文件不是 UTF-8 文本，无法按 Markdown 预览') }
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
  const document = await pdfjs.getDocument({ data: buffer!.slice() }).promise
  pdf.value = document as any
  pdfPages.value = document.numPages
  pdfPage.value = 1
  await nextTick()
  await paintPdf()
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
}

async function renderSheet() {
  // user:“什么东西都尽可能支持一下”+(用无 Worker 的通用入口读表格，避免前台 CSP 为 blob worker 开口子)。
  const { default: readXlsxFile } = await import('read-excel-file/universal')
  const workbook = await readXlsxFile(new Blob([arrayBuffer()], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
  // user:“什么东西都尽可能支持一下”+(表格按工作表分页显示；超大表只渲染前几行几列，避免整块屏卡住)。
  sheets.value = workbook.map(({ sheet, data }) => ({ name: sheet, rows: data.slice(0, MAX_SHEET_ROWS).map(row => row.slice(0, MAX_SHEET_COLUMNS)) }))
  activeSheet.value = sheets.value[0]?.name || ''
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (value instanceof Date) return value.toLocaleString()
  return String(value)
}

function decodeXml(value: string): string {
  return value.replace(/&#(\d+);/g, (_, code: string) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_, code: string) => String.fromCharCode(parseInt(code, 16)))
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&')
}

function paragraphTexts(xml: string): string[] {
  const lines: string[] = []
  for (const match of xml.matchAll(/<a:p\b[\s\S]*?<\/a:p>/g)) {
    const text = [...match[0].matchAll(/<a:t>([\s\S]*?)<\/a:t>/g)].map(item => decodeXml(item[1]).trim()).filter(Boolean).join('')
    if (text) lines.push(text)
  }
  return lines
}

async function renderSlides() {
  const { unzipSync, strFromU8 } = await import('fflate')
  const files = unzipSync(new Uint8Array(arrayBuffer()))
  const slideNames = Object.keys(files)
    .filter(path => /^ppt\/slides\/slide\d+\.xml$/.test(path))
    .sort((a, b) => Number(a.match(/(\d+)\.xml$/)![1]) - Number(b.match(/(\d+)\.xml$/)![1]))
  slides.value = slideNames.map((path, index) => {
    const number = Number(path.match(/(\d+)\.xml$/)![1])
    const xml = strFromU8(files[path])
    const lines = paragraphTexts(xml)
    const notes = files[`ppt/notesSlides/notesSlide${number}.xml`] ? paragraphTexts(strFromU8(files[`ppt/notesSlides/notesSlide${number}.xml`])) : []
    // user:“什么东西都尽可能支持一下”+(PPT 内嵌图片也显示出来，至少能看到每一页的配图)。
    const rels = files[`ppt/slides/_rels/slide${number}.xml.rels`]
    const targets = new Map<string, string>()
    if (rels) {
      for (const relationship of strFromU8(rels).matchAll(/<Relationship\b[^>]*>/g)) {
        const id = /Id="([^"]+)"/.exec(relationship[0])?.[1]
        const target = /Target="([^"]+)"/.exec(relationship[0])?.[1]
        if (id && target && target.includes('media/')) targets.set(id, `ppt/${target.replace(/^\.\.\//, '')}`)
      }
    }
    const images: string[] = [], seen = new Set<string>()
    for (const embed of xml.matchAll(/<a:blip\b[^>]*(?:r:embed|r:link)="([^"]+)"/g)) {
      const media = targets.get(embed[1])
      const bytes = media ? files[media] : undefined
      if (!media || !bytes || seen.has(media)) continue
      seen.add(media)
      const url = URL.createObjectURL(new Blob([bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer], { type: mediaType(media) }))
      slideImageUrls.push(url); images.push(url)
    }
    return { index: index + 1, title: lines[0] || `第 ${index + 1} 页`, lines: lines.slice(1), notes, images }
  })
  // user:“什么东西都尽可能支持一下”+(PPT 没有浏览器端排版引擎时先给出完整文字大纲，图片版式仍可交给默认应用)。
  if (slides.value.length) notice.value = '演示文稿按文字大纲与内嵌图片预览；完整版式请使用默认应用打开'
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

function changeImageZoom(delta: number) {
  imageZoom.value = Math.min(400, Math.max(25, imageZoom.value + delta))
}

function fit() {
  if (kind.value === 'pdf') { pdfZoom.value = 100; void paintPdf() } else imageZoom.value = 100
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === '+' || event.key === '=') { event.preventDefault(); kind.value === 'pdf' ? changePdfZoom(25) : changeImageZoom(25) }
  else if (event.key === '-' || event.key === '_') { event.preventDefault(); kind.value === 'pdf' ? changePdfZoom(-25) : changeImageZoom(-25) }
  else if (event.key === '0') { event.preventDefault(); fit() }
}

async function openWithDefaultApp() {
  if (!props.transport) return
  error.value = ''
  try {
    const response = await props.transport.request<TransportHttpResponse>({
      kind: 'http', method: 'POST', path: '/files/open-reference',
      headers: { 'Content-Type': 'application/json' },
      body: new TextEncoder().encode(JSON.stringify({ path: props.tab.resource, work_root: props.root })),
    })
    if (response.status < 200 || response.status >= 300) throw new Error(detailOf(response, '文件无法打开'))
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '文件无法打开' }
}

const canZoom = computed(() => kind.value === 'image' || kind.value === 'pdf')
const zoomValue = computed(() => kind.value === 'pdf' ? pdfZoom.value : imageZoom.value)
function zoomBy(delta: number) { kind.value === 'pdf' ? changePdfZoom(delta) : changeImageZoom(delta) }

onMounted(() => { mounted = true; void open() })
watch(() => [props.tab.resource, props.root], () => { if (mounted) void open() })
onBeforeUnmount(() => { generation++; releaseVisual() })
</script>
<template>
  <div class="split-preview" tabindex="-1" @keydown="onKeydown">
    <div class="split-content-toolbar">
      <span class="split-path" :title="tab.resource">{{ name }}</span>
      <span class="split-preview-kind">{{ kindLabel }}</span>
      <template v-if="canZoom">
        <button class="split-icon-button" type="button" title="缩小" aria-label="缩小预览" :disabled="!blobUrl && !pdfPages" @click="zoomBy(-25)"><Minus :size="14" /></button>
        <span class="split-preview-zoom" aria-live="polite">{{ zoomValue }}%</span>
        <button class="split-icon-button" type="button" title="放大" aria-label="放大预览" :disabled="!blobUrl && !pdfPages" @click="zoomBy(25)"><Plus :size="14" /></button>
        <button class="split-icon-button" type="button" title="适应窗口 · 按 0" aria-label="适应窗口" :disabled="!blobUrl && !pdfPages" @click="fit"><RotateCcw :size="14" /></button>
      </template>
      <button v-if="kind === 'markdown' && controller" class="split-icon-button" type="button" title="在文本编辑器中编辑" aria-label="在文本编辑器中编辑" @click="editInSplit"><Pencil :size="14" /></button>
      <button class="split-icon-button" type="button" title="重新读取" aria-label="重新读取" @click="open"><RefreshCw :size="14" /></button>
      <button class="split-icon-button" type="button" title="使用默认应用打开" aria-label="使用默认应用打开" @click="openWithDefaultApp"><ExternalLink :size="14" /></button>
    </div>
    <p v-if="error" class="split-content-error" role="alert">{{ error }}<button v-if="!loading" class="split-text-button" @click="open">重试</button></p>
    <p v-else-if="notice" class="split-content-notice">{{ notice }}</p>
    <p v-if="loading" class="split-content-notice" role="status">正在打开文件…</p>
    <div v-else-if="!tab.resource" class="split-empty"><FileQuestion :size="22" /><span>从文件树选择文件后在这里预览</span></div>
    <div v-else-if="kind === 'markdown'" class="split-preview-body split-preview-body--markdown">
      <MarkdownRenderer class="split-preview-markdown" :content="markdownText" />
    </div>
    <div v-else-if="kind === 'image' && blobUrl" class="split-preview-body split-preview-body--media">
      <img :src="blobUrl" :alt="name" :style="{ width: `${imageZoom}%` }" @error="error = '图片解码失败，原文件可能格式不受支持或内容已损坏'">
    </div>
    <div v-else-if="kind === 'video' && blobUrl" class="split-preview-body split-preview-body--media">
      <video :src="blobUrl" controls preload="metadata" @error="error = '这个视频格式当前无法播放，请使用默认应用打开'">当前环境不支持视频播放</video>
    </div>
    <div v-else-if="kind === 'audio' && blobUrl" class="split-preview-body split-preview-body--media split-preview-body--audio">
      <audio :src="blobUrl" controls preload="metadata" @error="error = '这个音频格式当前无法播放，请使用默认应用打开'">当前环境不支持音频播放</audio>
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
      <div v-if="sheets.length > 1" class="split-preview-sheet-tabs" role="tablist" aria-label="工作表">
        <button v-for="sheet in sheets" :key="sheet.name" type="button" role="tab" :aria-selected="sheet.name === activeSheet" :class="{ active: sheet.name === activeSheet }" @click="activeSheet = sheet.name">{{ sheet.name }}</button>
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
    <div v-else-if="kind === 'pptx'" class="split-preview-body split-preview-body--document">
      <article v-for="slide in slides" :key="slide.index" class="split-preview-slide">
        <header><span class="split-preview-slide-index">{{ slide.index }}</span><span>{{ slide.title }}</span></header>
        <p v-for="(line, index) in slide.lines" :key="index">{{ line }}</p>
        <div v-if="slide.images.length" class="split-preview-slide-images">
          <img v-for="src in slide.images" :key="src" :src="src" alt="" loading="lazy" />
        </div>
        <footer v-if="slide.notes.length"><strong>备注</strong><p v-for="(line, index) in slide.notes" :key="index">{{ line }}</p></footer>
      </article>
      <p v-if="!slides.length" class="split-content-notice">这个演示文稿没有可显示的文字内容</p>
    </div>
    <div v-else-if="!error && !loading" class="split-empty">
      <FileQuestion :size="22" />
      <span>这个文件暂时无法预览</span>
      <button class="split-text-button" type="button" @click="openWithDefaultApp">使用默认应用打开</button>
    </div>
  </div>
</template>
