<template>
  <!-- user:“视频无法加载和播放，查修”+
       (灯箱原来把视频塞进 `sandbox=""` 的 iframe：那个沙箱里的媒体文档根本不渲染播放器，
        连加载状态都看不到。音视频改成和分屏一样的原生 `<video>` / `<audio>`，
        加载、报错、重试都在我们手里)。 -->
  <div class="preview-media" :class="`preview-media--${family}`" data-preview-media>
    <div v-if="family === 'video'" class="preview-media__stage">
      <video
        :key="frameKey"
        ref="mediaEl"
        class="preview-media__video"
        :src="src"
        controls
        playsinline
        preload="metadata"
        @loadedmetadata="onReady"
        @canplay="onReady"
        @error="onError"
      />
      <div v-if="!ready && !failure" class="preview-media__status" role="status">
        <span class="preview-media__spinner" aria-hidden="true" />
        <span>正在载入视频…</span>
      </div>
      <p v-if="failure" class="preview-media__error" role="alert">
        <span>{{ failure }}</span>
        <button type="button" @click="reload">重试</button>
      </p>
    </div>

    <div v-else class="preview-media__stage preview-media__stage--audio">
      <div class="preview-media__card">
        <span class="preview-media__name" :title="title">{{ title }}</span>
        <audio
          :key="frameKey"
          ref="mediaEl"
          class="preview-media__audio"
          :src="src"
          controls
          preload="metadata"
          @loadedmetadata="onReady"
          @canplay="onReady"
          @error="onError"
        />
        <p v-if="failure" class="preview-media__error" role="alert">
          <span>{{ failure }}</span>
          <button type="button" @click="reload">重试</button>
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 灯箱里的音视频播放器（原生 `<video>` / `<audio>`）。
 *
 * user:“视频无法加载和播放，查修”+(不用 iframe：沙箱 iframe 里的媒体文档既没有加载反馈，
 * 也没有我们能控的错误状态；原生元素能读到 `error.code`，出问题能说清是格式还是读取失败)。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  src: string
  mime: string
  title?: string
  /** 多久还没拿到元数据算失败；测试里可以调小。 */
  loadTimeoutMs?: number
}>(), {
  title: '',
  loadTimeoutMs: 20000,
})

const family = computed(() => (props.mime.startsWith('audio/') ? 'audio' : 'video'))
const mediaEl = ref<HTMLMediaElement | null>(null)
const ready = ref(false)
const failure = ref('')
const frameKey = ref(0)
let timer: ReturnType<typeof setTimeout> | undefined

function clearTimer(): void {
  if (timer !== undefined) { clearTimeout(timer); timer = undefined }
}

function armTimer(): void {
  clearTimer()
  const limit = props.loadTimeoutMs
  if (!Number.isFinite(limit) || limit <= 0) return
  timer = setTimeout(() => {
    timer = undefined
    if (!ready.value) failure.value = '音视频在预期时间内没有载入，可能是文件不存在或格式不受支持'
  }, limit)
}

/** MediaError 的数值给一句人话：格式、网络、解码分别对应不同的出路。 */
function describeError(element: HTMLMediaElement): string {
  const code = element.error?.code
  if (code === 1) return '播放被中断，可以重试一次'
  if (code === 2) return '读取音视频时出错，文件可能被移动或权限不足'
  if (code === 3) return '解码失败，这个音视频的编码可能不受支持'
  if (code === 4) return '这个音视频格式当前无法播放，可以先用「外部打开」'
  return '音视频无法播放'
}

function onReady(): void {
  clearTimer()
  ready.value = true
  failure.value = ''
}

function onError(): void {
  clearTimer()
  const element = mediaEl.value
  ready.value = false
  failure.value = element ? describeError(element) : '音视频无法播放'
}

function reload(): void {
  ready.value = false
  failure.value = ''
  frameKey.value += 1
  armTimer()
}

watch(() => props.src, () => { reload() }, { immediate: true })
onBeforeUnmount(clearTimer)

defineExpose({ reload })
</script>

<style scoped>
.preview-media {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--theme-main-sunken-background);
  color: var(--theme-main-text);
}

.preview-media__stage {
  position: relative;
  display: grid;
  place-items: center;
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--space-3);
  overflow: auto;
}

.preview-media__video {
  display: block;
  max-width: 100%;
  max-height: 100%;
  border-radius: var(--radius-sm);
  background: #000;
}

.preview-media__stage--audio {
  align-content: center;
}

.preview-media__card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  width: min(560px, 100%);
  padding: var(--space-5) var(--space-4);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--theme-main-text) 4%, transparent);
}

.preview-media__name {
  overflow: hidden;
  max-width: 100%;
  font-size: 12.5px;
  font-weight: 640;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-media__audio {
  width: 100%;
}

.preview-media__status {
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

.preview-media__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid color-mix(in srgb, var(--theme-main-text) 24%, transparent);
  border-top-color: color-mix(in srgb, var(--theme-main-text) 68%, transparent);
  border-radius: 50%;
  animation: preview-media-spin 900ms linear infinite;
}

@keyframes preview-media-spin {
  to { transform: rotate(360deg); }
}

.preview-media__error {
  position: absolute;
  left: 50%;
  bottom: var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  max-width: min(520px, 90%);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-background) 92%, transparent);
  color: color-mix(in srgb, var(--theme-main-text) 82%, transparent);
  font-size: 12px;
  transform: translateX(-50%);
  box-shadow: var(--shadow-sm);
}

.preview-media__error button {
  flex: none;
  height: 24px;
  border: 0;
  border-radius: 999px;
  padding: 0 var(--space-2);
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}

@media (prefers-reduced-motion: reduce) {
  .preview-media__spinner { animation-duration: 0ms; }
}
</style>
