<template>
  <div class="preview-surface" :class="{ 'preview-surface--inert': !interactive }">
    <!-- user:“预览器统一成一个浏览器表面”+(灯箱与将来的浏览器工作区共用这一块显示面；
         组件自己不知道被放在哪，只按三态把内容画出来。注释必须留在根元素内部——
         Vue 3 把根级注释也算一个根节点，根上的状态类会因此落到片段上而失效)。 -->

    <!-- user:“灯箱应该配套缩放UI…默认大小自适应，左键可拖动”+
         (图片不再塞进 iframe 交给浏览器自带的图片文档：那里没有我们能控的缩放、拖动和标注。
          换成原生查看器，其他类型仍走 iframe，一条三态判定不变)。 -->
    <PreviewImageViewer
      v-if="imageDocument"
      ref="imageViewer"
      :src="imageSource || imageDocument.url"
      :name="imageDocument.title"
      :annotating="annotating"
      :load-original="loadOriginal"
      :load-timeout-ms="loadTimeoutMs"
      @update:annotating="$emit('update:annotating', $event)"
      @annotations-change="$emit('annotations-change', $event)"
    />

    <!-- user:“视频无法加载和播放，查修”+
         (音视频也不能走 iframe：`sandbox=""` 里的媒体文档既不出播放器、也没有加载反馈。
          改成原生播放器，其余类型仍是同一块 iframe 表面)。 -->
    <PreviewMediaPlayer
      v-else-if="mediaDocument"
      ref="mediaPlayer"
      :src="mediaSource || mediaDocument.url"
      :mime="mediaDocument.mime"
      :title="mediaDocument.title"
      :load-timeout-ms="loadTimeoutMs"
    />

    <!-- user:“除了Office类，别的都把它修好”+
         (PDF 交给 pdfjs 自己画：浏览器内置查看器在沙箱 iframe / WebView 里不可靠，
          也拿不到加载失败的原因)。 -->
    <PreviewPdfViewer
      v-else-if="pdfDocument"
      ref="pdfViewer"
      :load-bytes="loadBytes"
      :title="pdfDocument.title"
      :load-timeout-ms="loadTimeoutMs"
    />

    <!-- user:“除了Office类，别的都把它修好”+(文本/JSON/CSV 自己解码显示，不再靠 iframe)。 -->
    <PreviewTextViewer
      v-else-if="textDocument"
      ref="textViewer"
      :load-bytes="loadBytes"
      :title="textDocument.title"
    />

    <template v-else-if="document && document.mode !== 'unsupported'">
      <div v-if="!ready && !failure" class="preview-surface__status" role="status">
        <span class="preview-surface__spinner" aria-hidden="true" />
        <span>{{ loadingLabel }}</span>
      </div>
      <p v-if="failure" class="preview-surface__error" role="alert">
        <span class="preview-surface__error-text">{{ failure }}</span>
        <button type="button" class="preview-surface__action" @click="reload">重试</button>
      </p>
      <iframe
        :key="frameKey"
        class="preview-surface__frame"
        :src="document.mode === 'native' ? document.url : undefined"
        :srcdoc="document.mode === 'rendered' ? document.html : undefined"
        :title="document.title || '预览'"
        :sandbox="frameSandbox"
        referrerpolicy="no-referrer"
        @load="onFrameLoad"
      />
    </template>

    <div v-else-if="document" class="preview-surface__unsupported">
      <p class="preview-surface__reason" role="alert">{{ document.reason }}</p>
      <span class="preview-surface__actions">
        <button
          v-if="canOpenWithDefaultApp"
          type="button"
          class="preview-surface__action preview-surface__action--primary"
          @click="$emit('open-default')"
        >用默认应用打开</button>
        <button
          v-if="canHandOff"
          type="button"
          class="preview-surface__action"
          @click="$emit('open-browser')"
        >用浏览器打开</button>
      </span>
    </div>

    <div v-else-if="busy" class="preview-surface__status" role="status">
      <span class="preview-surface__spinner" aria-hidden="true" />
      <span>{{ loadingLabel }}</span>
    </div>

    <div v-else class="preview-surface__empty" role="status">选择一个文件后在这里查看</div>
  </div>
</template>

<script setup lang="ts">
/**
 * user:“浏览器表面组件：native → iframe :src，rendered → iframe :srcdoc”+
 * (音视频、PDF、纯文本与转换出来的 HTML 都交给浏览器自己显示，不再为每种类型各写一套查看器；
 * 转换出来的 HTML 一律去脚本、去外链，用 sandbox 兜底。)
 *
 * user:“灯箱应该配套缩放UI，支持Ctrl滚轮…默认大小自适应，左键可拖动”+
 * (图片是唯一的例外：交给浏览器图片文档就再也控不了缩放、拖动与标注，
 *  所以图片走 `PreviewImageViewer`，其余类型仍是同一块 iframe 表面。)
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import PreviewImageViewer from './PreviewImageViewer.vue'
import PreviewMediaPlayer from './PreviewMediaPlayer.vue'
import PreviewPdfViewer from './PreviewPdfViewer.vue'
import PreviewTextViewer from './PreviewTextViewer.vue'
import type { PreviewDocument } from './resolve'

const props = withDefaults(defineProps<{
  document: PreviewDocument | null
  /** 卡片等嵌入式场景先关掉交互；灯箱与分屏按默认 true。 */
  interactive?: boolean
  /** unsupported 时是否提供「用默认应用打开」。 */
  canOpenWithDefaultApp?: boolean
  /** 目标其实是外部网址时是否提供「用浏览器打开」。 */
  canHandOff?: boolean
  loadingLabel?: string
  /** 目标已确定、内容还在解析（例如转换）。避免解析期间闪一下"空状态"文案。 */
  busy?: boolean
  /** 帧多久没加载完成算失败；测试里调小，正常不用传。 */
  loadTimeoutMs?: number
  /** 图片的标注模式：由灯箱头部控制，这里只转发给查看器。 */
  annotating?: boolean
  /** 原始字节：查看器合成标注图时用它重新解码（避免跨源画布污染）。 */
  loadOriginal?: (() => Promise<Blob>) | null
  /** 原始字节：PDF 由 pdfjs 自己画，需要完整字节。 */
  loadBytes?: (() => Promise<Uint8Array>) | null
  /** 宿主已经取到字节并做好的 blob 地址（安卓没有 /api 代理，图片/音视频必须走这条）。 */
  imageSource?: string
  mediaSource?: string
}>(), {
  interactive: true,
  canOpenWithDefaultApp: false,
  canHandOff: false,
  loadingLabel: '正在载入…',
  busy: false,
  loadTimeoutMs: 20000,
  annotating: false,
  loadOriginal: null,
  loadBytes: null,
  imageSource: '',
  mediaSource: '',
})

defineEmits<{
  'open-default': []
  'open-browser': []
  'update:annotating': [value: boolean]
  'annotations-change': [count: number]
}>()

const ready = ref(false)
const failure = ref('')
// 重新加载用替换 key 的方式重建帧：iframe 的 src 不变时浏览器不会重读。
const frameKey = ref(0)
const imageViewer = ref<InstanceType<typeof PreviewImageViewer> | null>(null)
const mediaPlayer = ref<InstanceType<typeof PreviewMediaPlayer> | null>(null)
const pdfViewer = ref<InstanceType<typeof PreviewPdfViewer> | null>(null)
const textViewer = ref<InstanceType<typeof PreviewTextViewer> | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined

/** 图片走原生查看器：三态判定仍是同一份，只有呈现方式不同。 */
const imageDocument = computed(() => {
  const doc = props.document
  return doc && doc.mode === 'native' && doc.mime.startsWith('image/') ? doc : null
})

/** 音视频走原生播放器（沙箱 iframe 里的媒体文档不出播放器，也拿不到错误状态）。 */
const mediaDocument = computed(() => {
  const doc = props.document
  if (!doc || doc.mode !== 'native') return null
  return doc.mime.startsWith('video/') || doc.mime.startsWith('audio/') ? doc : null
})

/** PDF 走 pdfjs 画布。 */
const pdfDocument = computed(() => {
  const doc = props.document
  return doc && doc.mode === 'native' && doc.mime === 'application/pdf' ? doc : null
})

/** 纯文本（含 json/csv/日志）走只读文本查看器。 */
const textDocument = computed(() => {
  const doc = props.document
  return doc && doc.mode === 'native' && doc.mime.startsWith('text/') ? doc : null
})


/**
 * user:“iframe 一律 sandbox 且只给必要权限”+
 * (图片/文本/音视频不需要脚本；PDF 的浏览器内置查看器需要脚本，但永远不给
 * allow-same-origin——帧拿到的是独立源，碰不到应用自身。)
 */
const frameSandbox = computed(() => {
  const doc = props.document
  if (!doc || doc.mode === 'unsupported') return ''
  if (!props.interactive) return ''
  return doc.mode === 'native' && doc.mime === 'application/pdf' ? 'allow-scripts' : ''
})

function clearTimer(): void {
  if (timer !== undefined) { clearTimeout(timer); timer = undefined }
}

function armTimer(): void {
  clearTimer()
  const limit = props.loadTimeoutMs
  if (!Number.isFinite(limit) || limit <= 0) return
  timer = setTimeout(() => {
    timer = undefined
    if (!ready.value) failure.value = '内容在预期时间内没有载入，可能是文件不存在或格式不受支持'
  }, limit)
}

function reset(): void {
  ready.value = false
  failure.value = ''
  clearTimer()
  // 图片/音视频/PDF 由各自组件负责载入超时；iframe 才需要这层兜底。
  if (props.document && props.document.mode !== 'unsupported'
    && !imageDocument.value && !mediaDocument.value && !pdfDocument.value && !textDocument.value) armTimer()
}

function onFrameLoad(): void {
  clearTimer()
  failure.value = ''
  ready.value = true
}

/** 对外暴露：工具栏上的「重新读取」。图片/音视频交给各自的查看器重读，不重建 iframe。 */
function reload(): void {
  if (imageDocument.value) { imageViewer.value?.reload(); return }
  if (mediaDocument.value) { mediaPlayer.value?.reload(); return }
  if (pdfDocument.value) { pdfViewer.value?.reload(); return }
  if (textDocument.value) { textViewer.value?.reload(); return }
  reset()
  frameKey.value += 1
}

watch(() => props.document, reset, { immediate: true })
onBeforeUnmount(clearTimer)

defineExpose({ reload, imageViewer, mediaPlayer, pdfViewer, textViewer })
</script>

<style scoped>
.preview-surface {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  flex: 1 1 auto;
  background: var(--theme-main-background);
  color: var(--theme-main-text);
}

.preview-surface__frame {
  flex: 1 1 auto;
  width: 100%;
  min-height: 0;
  border: 0;
  background: var(--theme-main-background);
}

.preview-surface--inert .preview-surface__frame {
  pointer-events: none;
}

.preview-surface__status {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  font-size: 12px;
  pointer-events: none;
}

.preview-surface__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid color-mix(in srgb, var(--theme-main-text) 24%, transparent);
  border-top-color: color-mix(in srgb, var(--theme-main-text) 68%, transparent);
  border-radius: 50%;
  animation: preview-surface-spin 900ms linear infinite;
}

@keyframes preview-surface-spin {
  to { transform: rotate(360deg); }
}

.preview-surface__error,
.preview-surface__reason {
  margin: 0;
  padding: var(--space-4);
  color: color-mix(in srgb, var(--theme-main-text) 78%, transparent);
  font-size: 12px;
  line-height: 1.6;
}

.preview-surface__error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.preview-surface__unsupported,
.preview-surface__empty {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-4);
}

.preview-surface__empty {
  align-items: center;
  color: color-mix(in srgb, var(--theme-main-text) 52%, transparent);
  font-size: 12px;
}

.preview-surface__actions {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: 0 var(--space-4) var(--space-4);
}

.preview-surface__unsupported .preview-surface__actions {
  padding: 0;
}

.preview-surface__action {
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

.preview-surface__action:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent);
}

.preview-surface__action--primary {
  background: var(--theme-control-background);
  color: var(--theme-control-text);
}

.preview-surface__action--primary:hover {
  background: var(--theme-control-background);
  filter: brightness(.94);
}

@media (prefers-reduced-motion: reduce) {
  .preview-surface__spinner { animation-duration: 0ms; }
}
</style>
