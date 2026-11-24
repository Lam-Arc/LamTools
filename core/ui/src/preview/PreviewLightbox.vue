<template>
  <!-- user:“灯箱：浮层盖在会话上，看完即关，不打断对话”+
       (Teleport 到 body 之外：会话里的滚动容器、transform 父级都不会再把浮层裁掉或困住)。 -->
  <Teleport to="body">
    <Transition name="preview-lightbox" @after-leave="onAfterLeave">
      <div
        v-if="open"
        ref="backdropEl"
        class="preview-lightbox__backdrop"
        data-preview-lightbox
        @keydown.esc.prevent.stop="requestClose"
        @click.self="requestClose"
      >
        <!-- user:“确保视觉、功能和交互不退化”+(打开时让对话框接收焦点，Escape 和焦点循环立即可用)。 -->
        <section
          ref="dialogEl"
          class="preview-lightbox"
          role="dialog"
          tabindex="-1"
          aria-modal="true"
          :aria-label="`预览：${title}`"
          @keydown.tab="trapDialogTab"
        >
          <header class="preview-lightbox__header">
            <span class="preview-lightbox__title" :title="targetPath || title">{{ title }}</span>
            <span v-if="kindLabel" class="preview-lightbox__kind">{{ kindLabel }}</span>
            <span v-if="canStep" class="preview-lightbox__kind preview-lightbox__counter" data-preview-counter>{{ siblingIndex + 1 }} / {{ siblings.length }}</span>
            <span class="preview-lightbox__spacer" aria-hidden="true" />
            <span v-if="hint" class="preview-lightbox__hint" role="status" data-preview-hint>{{ hint }}</span>
            <!-- user:“「在分屏中打开」按钮先不做（或只在 UI 上隐藏），等浏览器模块提供工作区后接”+
                 (分屏与标签系统将由浏览器模块统一接管，现在接等于返工；这里刻意留空位不渲染)。 -->

            <!-- user:“灯箱应该配套缩放UI，支持Ctrl滚轮，提供复制/外部打开键，默认大小自适应，左键可拖动”+
                 (缩放与拖动在图片区自己的工具坞里；这里只放“对这张图做什么”的动作)。
                 user:“支持修改标注…『引用』，直接将已标注/未标注则为原图直接加入输入框”+
                 (标注是模式开关；复制与引用都按“有标注给合成图、没标注给原图”取值)。 -->
            <template v-if="isImage">
              <button
                type="button"
                class="preview-lightbox__action"
                :class="{ 'is-active': annotating }"
                :aria-pressed="annotating"
                data-preview-annotate
                @click="toggleAnnotate"
              >{{ annotating ? '完成标注' : '标注' }}</button>
              <button
                type="button"
                class="preview-lightbox__action"
                :disabled="busyAction"
                data-preview-copy
                @click="copyImage"
              >{{ copyLabel }}</button>
              <button
                v-if="composer"
                type="button"
                class="preview-lightbox__action"
                :disabled="busyAction || !composerReady"
                :title="composerReady ? '把这张图加入输入框' : '先选择一个会话'"
                data-preview-reference
                @click="referenceImage"
              >引用</button>
              <button
                v-if="target?.kind === 'file'"
                type="button"
                class="preview-lightbox__action"
                data-preview-open
                @click="openWithDefaultApp"
              >外部打开</button>
            </template>

            <button
              v-if="actionable.document"
              type="button"
              class="preview-lightbox__action"
              @click="openWithDefaultApp"
            >用默认应用打开</button>
            <button
              v-if="actionable.browser"
              type="button"
              class="preview-lightbox__action"
              @click="openInBrowser"
            >用浏览器打开</button>
            <!-- user:“文件树、资料库、预览器里对文件加「发送到设备」”+
                 (预览器也是文件的一个落点；这里只开入口，发送与否由统一的设备清单判断)。 -->
            <button
              v-if="target?.kind === 'file'"
              type="button"
              class="preview-lightbox__action"
              data-preview-send
              @click="sendOpen = true"
            >发送到设备</button>
            <button
              ref="closeButtonEl"
              type="button"
              class="preview-lightbox__close"
              title="关闭 · Esc"
              aria-label="关闭预览"
              @click="requestClose"
            >
              <X :size="15" />
            </button>
          </header>
          <PreviewSurface
            ref="surfaceEl"
            :document="resolved"
            :can-open-with-default-app="actionable.document"
            :can-hand-off="actionable.browser"
            :busy="resolving"
            :annotating="annotating"
            :load-original="loadOriginalImage"
            :load-bytes="loadPreviewBytes"
            :image-source="blobSource"
            :media-source="blobSource"
            loading-label="正在载入预览…"
            @update:annotating="annotating = $event"
            @annotations-change="annotationCount = $event"
            @open-default="openWithDefaultApp"
            @open-browser="openInBrowser"
          />
          <!-- user:“灯箱加上切换用的左右键”+(同目录同类文件的上一张/下一张，覆盖在内容两侧)。 -->
          <button
            v-if="canStep"
            type="button"
            class="preview-lightbox__nav preview-lightbox__nav--prev"
            aria-label="上一个文件"
            :title="siblingName(-1)"
            data-preview-step="prev"
            @click="step(-1)"
          >‹</button>
          <button
            v-if="canStep"
            type="button"
            class="preview-lightbox__nav preview-lightbox__nav--next"
            aria-label="下一个文件"
            :title="siblingName(1)"
            data-preview-step="next"
            @click="step(1)"
          >›</button>

          <!-- user:“选中后开始传输”+(名单自带「为什么不能发」，靠在灯箱里不打断预览)。 -->
          <div v-if="sendOpen" class="preview-lightbox__send" data-preview-send-layer @click.stop>
            <SendToDeviceMenu
              :path="targetPath"
              @sent="sendOpen = false"
              @close="sendOpen = false"
            />
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
/**
 * user:“预览器统一成一个浏览器表面，用两种形态承载：灯箱 / 分屏”+
 * (灯箱只呈现 resolve 给出的本地内容：没有地址栏、没有前进后退、不加载任意外部站点。
 * 网页浏览是浏览器模块的职责，这里只留一个「用浏览器打开」的出口。)
 *
 * user:“同一目标能在两种形态间切换”+(目标由 target.ts 描述，灯箱只管把它交给
 * PreviewSurface 呈现；换成别的宿主时看到的仍是同一份内容。)
 *
 * user:“灯箱应该配套缩放UI，支持Ctrl滚轮，提供复制/外部打开键，默认大小自适应，左键可拖动”+
 * (图片的呈现从 iframe 换成原生查看器后，缩放/拖动/标注都在查看器里；
 *  这个文件负责头部动作与“把当前这张图取出来”的唯一入口。)
 */
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { X } from 'lucide-vue-next'
import PreviewSurface from './PreviewSurface.vue'
import SendToDeviceMenu from '@/components/SendToDeviceMenu.vue'
import { canHandOffToBrowser, handOffToBrowser, isBrowserHandoffUrl } from './browserHandoff'
import { PREVIEW_COMPOSER_KEY } from './composerBridge'
import { copyImageBlob } from './imageClipboard'
import {
  previewMimeLabel,
  previewRasterPath,
  previewReadPath,
  resolvePreviewDocument,
  type PreviewDocument,
} from './resolve'
import { baseName } from './route'
import { listPreviewSiblings } from './siblings'
import { createPreviewTransport } from './transport'
import { previewTargetPath, type PreviewTarget } from './target'
import { resolvePreviewRoute } from './route'
import { openFileInSplit } from '@/split/openFile'
import { useOptionalWorkspace } from '@/workspace/context'
import {
  closePreviewLightbox,
  switchPreviewTarget,
  registerPreviewLightboxHost,
  resetPreviewLightbox,
  restorePreviewLightboxFocus,
  usePreviewLightbox,
} from './usePreviewLightbox'
import { trapDialogTab } from '@/composables/trapDialogTab'
import { backendOriginUrl } from '@/plugins/assets'
import { openFileWithDefaultApp } from '@/split/openFile'
import type { LamToolsTransport } from '@/transport'
import type { PreviewResolveTransport } from './resolve'

/** 解析方式默认走真实链路；展厅/测试可以注入本地示例，不去碰真实文件。 */
export type PreviewResolver = (target: PreviewTarget, transport: PreviewResolveTransport) => Promise<PreviewDocument>

const props = withDefaults(defineProps<{
  transport?: LamToolsTransport
  resolver?: PreviewResolver | null
}>(), { resolver: null })

const { target, open, title } = usePreviewLightbox()
const targetPath = computed(() => previewTargetPath(target.value))
const composer = inject(PREVIEW_COMPOSER_KEY, null)

/**
 * user:“Office走分屏路径，自动打开分屏或为已有分屏增加标签页”+
 * (灯箱只能看媒体与文本；docx/xlsx/pptx 这类只有分屏的渲染器能画。与其停在这里
 *  说“看不了”，不如把这份文件直接交给分屏：没有分屏就开一块，有就往里加标签。)
 */
const workspace = useOptionalWorkspace()

function handOffToSplit(target: PreviewTarget | null): boolean {
  if (!workspace || !target || target.kind !== 'file' || !target.path) return false
  // 只交接分屏真能渲染的文档；压缩包、旧版 doc 之类仍留在灯箱里说明原因。
  if (resolvePreviewRoute(target.path).kind !== 'local') return false
  return Boolean(openFileInSplit(workspace, target.path, { workRoot: target.workRoot || '', force: true }))
}

interface ImageViewerHandle {
  hasAnnotations: () => boolean
  exportBlob: () => Promise<Blob>
  reload: () => void
  fit: () => void
  focusStage: () => void
}

const dialogEl = ref<HTMLElement | null>(null)
const backdropEl = ref<HTMLElement | null>(null)
const surfaceEl = shallowRef<{ reload: () => void; imageViewer?: ImageViewerHandle | null } | null>(null)
const resolved = ref<PreviewDocument | null>(null)
const resolving = ref(false)
/** user:“发送到设备”+(入口开关；清单自己做资格判定与错误说明)。 */
const sendOpen = ref(false)
/** 图片的标注模式与标注数量：头部据此切换按钮文案与可用的动作。 */
const annotating = ref(false)
const annotationCount = ref(0)
/** 同目录同类文件的序列：左右键在它上面走，-1 表示没对上。 */
const siblings = ref<PreviewTarget[]>([])
const siblingIndex = ref(-1)
let siblingGeneration = 0
const busyAction = ref(false)
const copyDone = ref(false)
const hint = ref('')
let hintTimer: ReturnType<typeof setTimeout> | undefined
let generation = 0
let unregisterHost: (() => void) | null = null

// user:“图片解码失败，原文件可能格式不受支持或内容已损坏”+(根因是安卓外壳没有 /api 代理：
// 图片/视频的 <img>/<video> 直接请求相对地址，拿到的是网页本身。这里用 IPC 读原始字节，
// 换成 blob 地址交给查看器；桌面拿到的是完整 http 地址，保持原样)。
const blobSource = ref('')
let blobKey = ''
/**
 * 已创建的 blob 地址集合：这一轮预览里不撤销任何一个。
 * 撤销旧地址会和查看器的加载抢时序（<img> 会直接报 Failed to fetch），
 * 体积又只有几百 KB，统一在灯箱卸载时释放即可。
 */
const blobUrls = new Set<string>()
watch([resolved, target, resolving], async ([doc, current, loading], _, onCleanup) => {
  if (loading || !doc || doc.mode !== 'native' || !doc.url.startsWith('/api/')
    || current?.kind !== 'file' || !current.path) {
    blobSource.value = ''
    blobKey = ''
    return
  }
  const isMedia = doc.mime.startsWith('image/') || doc.mime.startsWith('audio/') || doc.mime.startsWith('video/')
  if (!isMedia) {
    blobSource.value = ''
    blobKey = ''
    return
  }
  const readPath = previewReadPath(current.path, current.workRoot)
  const key = `${readPath}|${doc.mime}`
  if (blobKey === key && blobSource.value) return
  blobSource.value = ''
  blobKey = ''
  // user:“全部审查，提交，发布”+(旧文件晚到的读取结果不能覆盖已切换的预览)。
  let currentRead = true
  onCleanup(() => { currentRead = false })
  try {
    const bytes = await resolveTransport.value.read(readPath)
    if (!currentRead || resolved.value !== doc || target.value !== current) return
    const buffer = bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength
      ? bytes.buffer
      : bytes.slice().buffer
    const next = URL.createObjectURL(new Blob([buffer as ArrayBuffer], { type: doc.mime }))
    blobUrls.add(next)
    blobSource.value = next
    blobKey = key
  } catch {
    // 读不到就退回原地址，让查看器按它自己的方式报错。
  }
})

const kindLabel = computed(() => {
  const doc = resolved.value
  if (!doc) return ''
  if (doc.mode === 'native') return previewMimeLabel(doc.mime)
  if (doc.mode === 'rendered') return '文档'
  return '无法预览'
})

/** user:“灯箱应该配套缩放UI…提供复制/外部打开键”+(只有图片才有这几个动作)。 */
const isImage = computed(() => resolved.value?.mode === 'native' && resolved.value.mime.startsWith('image/'))
const copyLabel = computed(() => (busyAction.value ? '复制中…' : copyDone.value ? '已复制' : '复制'))
/** 标注模式下不切文件：切走就丢了正在画的东西。 */
const canStep = computed(() => siblings.value.length > 1 && siblingIndex.value >= 0 && !annotating.value)

function siblingName(delta: number): string {
  const total = siblings.value.length
  if (total < 2 || siblingIndex.value < 0) return ''
  const item = siblings.value[(siblingIndex.value + delta + total) % total]
  return item && item.kind === 'file' ? baseName(item.path) : ''
}

/** 换到同族的上一张/下一张；到头就绕回去。 */
function step(delta: number): void {
  const total = siblings.value.length
  if (!canStep.value || total < 2) return
  const next = (siblingIndex.value + delta + total) % total
  const item = siblings.value[next]
  if (!item) return
  siblingIndex.value = next
  switchPreviewTarget(item)
}

/**
 * user:“灯箱加上切换用的左右键”+(左右方向键直接翻；焦点可能落在按钮或 body 上，
 * 所以挂在 window 上，不依赖浮层内部焦点。输入框/文字块里不抢键)。
 */
function onWindowKeydown(event: KeyboardEvent): void {
  if (!open.value) return
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  const element = event.target as HTMLElement | null
  if (element && (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || element.isContentEditable)) return
  if (!canStep.value) return
  event.preventDefault()
  step(event.key === 'ArrowLeft' ? -1 : 1)
}

async function loadSiblings(): Promise<void> {
  const run = ++siblingGeneration
  siblings.value = []
  siblingIndex.value = -1
  const result = await listPreviewSiblings(target.value, props.transport)
  if (run !== siblingGeneration) return
  siblings.value = result.items
  siblingIndex.value = result.index
}

/** 引用需要一个能收附件的会话；没有时按钮如实禁用，而不是点了没反应。 */
const composerReady = computed(() => Boolean(composer?.canAttach()))

/** 只有文件目标能交给系统默认应用；只有外部网址能交给浏览器模块。 */
const actionable = computed(() => {
  const doc = resolved.value
  const fileTarget = target.value?.kind === 'file'
  const externalUrl = target.value?.kind === 'url' && isBrowserHandoffUrl(target.value.url)
  return {
    document: Boolean(doc && doc.mode === 'unsupported' && fileTarget),
    browser: Boolean(doc && doc.mode === 'unsupported' && externalUrl && canHandOffToBrowser()),
  }
})

/** 与解析层共用同一条通道：拼地址与读字节都不另开一条路。 */
const resolveTransport = computed(() => createPreviewTransport({ transport: props.transport, origin: backendOriginUrl() }))

async function resolveTarget(): Promise<void> {
  const run = ++generation
  const current = target.value
  if (!current) { resolved.value = null; return }
  resolving.value = true
  annotating.value = false
  annotationCount.value = 0
  try {
    const document_ = await (props.resolver ?? resolvePreviewDocument)(current, resolveTransport.value)
    if (run !== generation) return
    // Office 交给分屏，灯箱随即关闭（脚本里提前 return，finally 照常收尾）。
    if (document_.mode === 'unsupported' && handOffToSplit(current)) {
      closePreviewLightbox({ restoreFocus: false })
      return
    }
    resolved.value = document_
  } catch (cause) {
    if (run === generation) {
      resolved.value = {
        mode: 'unsupported',
        reason: cause instanceof Error ? cause.message : '内容无法预览',
        title: title.value,
      }
    }
  } finally {
    if (run === generation) resolving.value = false
  }
}

function flash(message: string): void {
  hint.value = message
  if (hintTimer) clearTimeout(hintTimer)
  hintTimer = setTimeout(() => { hint.value = ''; hintTimer = undefined }, 2800)
}

function requestClose(): void {
  closePreviewLightbox()
}

// user:“系统返回直接退出应用，人被困在预览里”+(灯箱是最上面一层，返回先关它)。
function onSystemBack(event: Event): void {
  if (!open.value) return
  event.preventDefault()
  requestClose()
}

function onAfterLeave(): void {
  // 过渡结束后再交还焦点并丢弃目标，避免关闭动画期间内容突然变空。
  restorePreviewLightboxFocus()
  resetPreviewLightbox()
}

async function openWithDefaultApp(): Promise<void> {
  const path = targetPath.value
  if (!path) return
  const scope = target.value?.kind === 'file' ? target.value.workRoot || '' : ''
  const opened = await openFileWithDefaultApp(props.transport, path, scope)
  if (!opened) surfaceEl.value?.reload()
}

async function openInBrowser(): Promise<void> {
  const current = target.value
  if (!current || current.kind !== 'url') return
  // user:“不要自己实现网页浏览，也不要在没有调用方时假装能用”+(没有浏览器模块接手时按钮不渲染)。
  await handOffToBrowser(current.url)
}

function toggleAnnotate(): void {
  annotating.value = !annotating.value
}

/**
 * 未标注时读原始字节（保留原格式与原文件名），标注后交给查看器合成 PNG。
 *
 * user:“『引用』，直接将已标注/未标注则为原图直接加入输入框”+
 * (原图路径走预览同一条读取通道，因此和灯箱里看到的是同一个文件；合成图只多一层标注)。
 */
async function originalImageBlob(doc: Extract<PreviewDocument, { mode: 'native' }>): Promise<Blob> {
  const current = target.value
  if (current?.kind === 'file') {
    // TIF/TIFF 走后端转码那条通道：读到的已经是 PNG，画布与复制都能用。
    const raster = doc.url.includes('/files/preview-image')
    const readPath = raster
      ? previewRasterPath(current.path, current.workRoot)
      : previewReadPath(current.path, current.workRoot)
    const bytes = await resolveTransport.value.read(readPath)
    const buffer = bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength
      ? bytes.buffer
      : bytes.slice().buffer
    return new Blob([buffer as ArrayBuffer], { type: doc.mime })
  }
  // 同样绕开 `<img>` 留下的 no-cors 缓存，见 preview/transport.ts 的说明。
  const response = await fetch(doc.url, { cache: 'no-store' }).catch(() => null)
  if (!response || !response.ok) throw new Error('图片读取失败，可以先「外部打开」再引用')
  return await response.blob()
}

/** 给查看器用的原始字节加载器：合成标注图时重新解码，避免跨源画布污染。 */
async function loadOriginalImage(): Promise<Blob> {
  const doc = resolved.value
  if (!doc || doc.mode !== 'native') throw new Error('图片还没有载入')
  return originalImageBlob(doc)
}

/** PDF 由 pdfjs 自己画：字节从预览通道读，和 markdown/office 同一条路。 */
async function loadPreviewBytes(): Promise<Uint8Array> {
  const current = target.value
  if (!current || current.kind !== 'file') throw new Error('这份 PDF 没有可读取的本机路径')
  return resolveTransport.value.read(previewReadPath(current.path, current.workRoot))
}

async function imagePayload(): Promise<{ blob: Blob; filename: string }> {
  const doc = resolved.value
  if (!doc || doc.mode !== 'native') throw new Error('图片还没有载入')
  const name = baseName(targetPath.value || doc.title) || 'image'
  const viewer = surfaceEl.value?.imageViewer
  if (viewer?.hasAnnotations()) {
    const blob = await viewer.exportBlob()
    return { blob, filename: `${name.replace(/\.[^.]+$/, '')}-标注.png` }
  }
  return { blob: await originalImageBlob(doc), filename: name }
}

async function copyImage(): Promise<void> {
  if (busyAction.value) return
  busyAction.value = true
  try {
    const { blob } = await imagePayload()
    await copyImageBlob(blob)
    copyDone.value = true
    setTimeout(() => { copyDone.value = false }, 1600)
    flash(annotationCount.value ? '已复制标注图' : '已复制原图')
  } catch (cause) {
    flash(cause instanceof Error ? cause.message : '复制失败')
  } finally {
    busyAction.value = false
  }
}

async function referenceImage(): Promise<void> {
  const bridge = composer
  if (!bridge || !bridge.canAttach() || busyAction.value) return
  busyAction.value = true
  try {
    const current = target.value
    const viewer = surfaceEl.value?.imageViewer
    // user:“现在本身就是存路径，可以直接把路径上传上去，走路径那条链路”+
    // (没标注 + 目标是磁盘文件：只交绝对路径，输入框按路径登记；不读字节、不复制、不 fetch)。
    if (current?.kind === 'file' && current.path && !viewer?.hasAnnotations()) {
      await bridge.attach([{ path: current.path, name: baseName(current.path) || 'image' }])
    } else {
      // 标注图是新生成的 PNG，没有磁盘路径，才退回字节上传。
      const { blob, filename } = await imagePayload()
      await bridge.attach([new File([blob], filename, { type: blob.type || 'image/png' })])
    }
    // 输入框此时已经接管焦点；关闭时不再把焦点还给打开灯箱的那个元素。
    closePreviewLightbox({ restoreFocus: false })
  } catch (cause) {
    flash(cause instanceof Error ? cause.message : '引用失败')
  } finally {
    busyAction.value = false
  }
}

watch(open, async isOpen => {
  if (!isOpen) {
    annotating.value = false
    annotationCount.value = 0
    return
  }
  await nextTick()
  dialogEl.value?.focus()
}, { immediate: true })

watch(target, () => {
  if (!open.value) return
  annotating.value = false
  annotationCount.value = 0
  void resolveTarget()
  void loadSiblings()
}, { immediate: true })

onMounted(() => {
  unregisterHost = registerPreviewLightboxHost()
  window.addEventListener('keydown', onWindowKeydown)
  window.addEventListener('sunday:back', onSystemBack)
})
onBeforeUnmount(() => {
  generation += 1
  for (const url of blobUrls) URL.revokeObjectURL(url)
  blobUrls.clear()
  window.removeEventListener('keydown', onWindowKeydown)
  window.removeEventListener('sunday:back', onSystemBack)
  if (hintTimer) clearTimeout(hintTimer)
  unregisterHost?.()
  unregisterHost = null
})
</script>

<style scoped>
/* user:“灯箱必须能被遮罩正常盖住、开合动画不跳”+
   (遮罩铺满整个窗口，层级用 --z-modal；动画只改透明度与轻微缩放，
   不动物理尺寸，避免打开瞬间内容被重新布局)。 */
.preview-lightbox__backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  padding: clamp(12px, 3vw, 40px);
  background: color-mix(in srgb, var(--theme-backdrop-text) 32%, transparent);
  backdrop-filter: blur(10px);
}

.preview-lightbox {
  position: relative;
  display: flex;
  flex-direction: column;
  width: min(1180px, 100%);
  height: min(88vh, 100%);
  overflow: hidden;
  border-radius: var(--radius-lg);
  background: var(--theme-main-background);
  box-shadow: var(--shadow-lg);
  color: var(--theme-main-text);
}

.preview-lightbox:focus {
  outline: none;
}

.preview-lightbox__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
}

.preview-lightbox__title {
  overflow: hidden;
  min-width: 0;
  font-size: 13px;
  font-weight: 680;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-lightbox__kind {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 2px var(--space-2);
  background: color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  color: color-mix(in srgb, var(--theme-main-text) 66%, transparent);
  font-size: 11px;
}

.preview-lightbox__spacer {
  flex: 1 1 auto;
}

.preview-lightbox__counter {
  font-variant-numeric: tabular-nums;
}

/* 左右切换：覆盖在内容两侧，不占布局；只在同目录有同类邻居时出现。 */
.preview-lightbox__nav {
  position: absolute;
  top: 50%;
  z-index: 3;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-background) 86%, transparent);
  color: color-mix(in srgb, var(--theme-main-text) 78%, transparent);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  transform: translateY(-50%);
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.preview-lightbox__nav:hover {
  background: color-mix(in srgb, var(--theme-main-background) 96%, transparent);
  color: var(--theme-main-text);
}

.preview-lightbox__nav--prev { left: var(--space-3); }
.preview-lightbox__nav--next { right: var(--space-3); }

/* 复制/引用这类动作的结果就地说明一句，不弹层、不打断预览。 */
.preview-lightbox__hint {
  flex: 0 1 auto;
  overflow: hidden;
  max-width: 260px;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  font-size: 11.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-lightbox__action {
  flex: 0 0 auto;
  height: 28px;
  border: 0;
  border-radius: 999px;
  padding: 0 var(--space-3);
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
  font: inherit;
  font-size: 12px;
  transition: background var(--dur-fast) var(--ease-out);
}

.preview-lightbox__action:hover:enabled {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent);
}

.preview-lightbox__action:disabled {
  opacity: 0.45;
  cursor: default;
}

/* 标注是模式：打开时按钮实心，和“做完了”区分的很清楚。 */
.preview-lightbox__action.is-active {
  background: var(--theme-control-background);
  color: var(--theme-control-text);
}

.preview-lightbox__close {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 70%, transparent);
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.preview-lightbox__close:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

/* 开合与项目现有浮层同一套时长与缓动，不新增令牌。 */
.preview-lightbox-enter-active,
.preview-lightbox-leave-active {
  transition: opacity var(--dur-base) var(--ease-out);
}

.preview-lightbox-enter-active .preview-lightbox,
.preview-lightbox-leave-active .preview-lightbox {
  transition: transform var(--dur-base) var(--ease-out), opacity var(--dur-base) var(--ease-out);
}

.preview-lightbox-enter-from,
.preview-lightbox-leave-to {
  opacity: 0;
}

.preview-lightbox-enter-from .preview-lightbox,
.preview-lightbox-leave-to .preview-lightbox {
  transform: scale(.985);
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .preview-lightbox-enter-active,
  .preview-lightbox-leave-active,
  .preview-lightbox-enter-active .preview-lightbox,
  .preview-lightbox-leave-active .preview-lightbox {
    transition-duration: 0ms;
  }
}
.preview-lightbox__send {
  position: absolute;
  top: 48px;
  right: 16px;
  z-index: 2;
}
/* user:“灯箱的动作条把关闭键挤出屏幕”+(窄屏让头部横向滚动，关闭键粘在右缘：
   动作再多也能关掉预览，不再依赖系统返回)。 */
@media (max-width: 640px) {
  .preview-lightbox__header {
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
  }

  .preview-lightbox__header::-webkit-scrollbar { display: none; }

  .preview-lightbox__close {
    position: sticky;
    right: 0;
    background: var(--theme-main-background);
    box-shadow: -10px 0 12px color-mix(in srgb, var(--theme-main-background) 90%, transparent);
  }
}
</style>
