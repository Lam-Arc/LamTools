<template>
  <!-- user:“除了Office类，别的都把它修好”+
       (纯文本/JSON/CSV 以前塞进 sandbox iframe：有的类型会被当成下载、有些 WebView 干脆空白。
        改成读字节自己解码，等宽正文 + 明确的失败原因)。 -->
  <div class="preview-text" data-preview-text>
    <div v-if="!ready && !failure" class="preview-text__status" role="status">
      <span class="preview-text__spinner" aria-hidden="true" />
      <span>正在载入文本…</span>
    </div>
    <p v-if="failure" class="preview-text__error" role="alert">
      <span>{{ failure }}</span>
      <button type="button" @click="reload">重试</button>
    </p>
    <pre v-if="ready" class="preview-text__body">{{ text }}</pre>
  </div>
</template>

<script setup lang="ts">
/**
 * 灯箱里的只读文本查看器（txt / json / csv / 日志…）。
 *
 * user:“除了Office类，别的都把它修好”+(文本类走 iframe 时，CSV 会被浏览器当成下载、
 * 沙箱里只剩空白；读字节自己解码，能显示也能说清编码问题)。
 */
import { ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  loadBytes?: (() => Promise<Uint8Array>) | null
  title?: string
  /** 超过这个大小就不整篇塞进内存。 */
  maxBytes?: number
}>(), {
  loadBytes: null,
  title: '',
  maxBytes: 4 * 1024 * 1024,
})

const text = ref('')
const ready = ref(false)
const failure = ref('')
let generation = 0

async function load(): Promise<void> {
  const run = ++generation
  ready.value = false
  failure.value = ''
  text.value = ''
  try {
    const loader = props.loadBytes
    if (!loader) throw new Error('这份文本没有可读取的通道')
    const bytes = await loader()
    if (run !== generation) return
    if (bytes.byteLength > props.maxBytes) throw new Error('文本超过 4 MB，预览已停用，可以用默认应用打开')
    text.value = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
    ready.value = true
  } catch (cause) {
    if (run !== generation) return
    failure.value = cause instanceof Error ? cause.message : '文本无法读取'
  }
}

function reload(): void {
  void load()
}

watch(() => props.loadBytes, () => { void load() }, { immediate: true })

defineExpose({ reload })
</script>

<style scoped>
.preview-text {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--theme-main-background);
  color: var(--theme-main-text);
}

.preview-text__body {
  flex: 1 1 auto;
  min-height: 0;
  margin: 0;
  padding: var(--space-4) var(--space-5);
  overflow: auto;
  color: color-mix(in srgb, var(--theme-main-text) 88%, transparent);
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.65;
  tab-size: 2;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.preview-text__status {
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

.preview-text__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid color-mix(in srgb, var(--theme-main-text) 24%, transparent);
  border-top-color: color-mix(in srgb, var(--theme-main-text) 68%, transparent);
  border-radius: 50%;
  animation: preview-text-spin 900ms linear infinite;
}

@keyframes preview-text-spin {
  to { transform: rotate(360deg); }
}

.preview-text__error {
  display: flex;
  flex: 1 1 auto;
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

.preview-text__error button {
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

@media (prefers-reduced-motion: reduce) {
  .preview-text__spinner { animation-duration: 0ms; }
}
</style>
