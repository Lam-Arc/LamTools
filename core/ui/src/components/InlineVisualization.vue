<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { inlineVisualizationRuntimeUrl } from '@/plugins/assets'
import { t } from '@/i18n'

const props = defineProps<{ source: string }>()
const frame = ref<HTMLIFrameElement | null>(null)
const height = ref(320), generation = ref(0), error = ref('')
let deadline: ReturnType<typeof setTimeout> | undefined
let themeObserver: MutationObserver | undefined
let initialized = false
function sendTheme() {
  const style = getComputedStyle(frame.value || document.documentElement)
  const read = (name: string) => style.getPropertyValue(name).trim()
  frame.value?.contentWindow?.postMessage({ type: 'sunday-visualization:theme', theme: {
    background: read('--theme-main-soft-background'), foreground: read('--theme-main-text'),
    control: read('--theme-control-background'), 'control-text': read('--theme-control-text'), border: read('--theme-main-border'),
  } }, '*')
}
// user:“不要出错”+(只处理本实例的高度与错误消息，不提供主程序操作或工具调用桥)。
function receive(event: MessageEvent) {
  if (!frame.value?.contentWindow || event.source !== frame.value.contentWindow || !event.data || typeof event.data !== 'object') return
  const data = event.data
  if (data.type === 'sunday-visualization:ready' && !initialized) {
    initialized = true
    frame.value.contentWindow.postMessage({ type: 'sunday-visualization:init', html: props.source }, '*')
  } else if (data.type === 'sunday-visualization:loaded') {
    clearTimeout(deadline); sendTheme()
  } else if (data.type === 'sunday-visualization:resize' && typeof data.height === 'number' && Number.isFinite(data.height)) {
    height.value = Math.min(800, Math.max(160, data.height))
  } else if (data.type === 'sunday-visualization:error') {
    clearTimeout(deadline); error.value = t('交互内容运行失败，可查看代码或重试')
  }
}
function start() {
  clearTimeout(deadline); initialized = false
  error.value = props.source.length > 262144 ? t('交互内容过大，请缩小后重试') : ''
  generation.value += 1
  if (!error.value) deadline = setTimeout(() => { error.value = t('交互内容未能加载，可查看代码或重试') }, 10000)
}
onMounted(() => {
  window.addEventListener('message', receive)
  themeObserver = new MutationObserver(sendTheme)
  // Theme variables live on the workspace shell, not necessarily on :root.
  for (let ancestor = frame.value?.parentElement; ancestor; ancestor = ancestor.parentElement) {
    themeObserver.observe(ancestor, { attributes: true, attributeFilter: ['class', 'style', 'data-theme'] })
  }
  start()
})
onBeforeUnmount(() => { clearTimeout(deadline); themeObserver?.disconnect(); window.removeEventListener('message', receive) })
</script>

<template>
  <section class="inline-visualization" :aria-label="t('交互内容')">
    <div v-if="error" class="inline-visualization-error" role="status">
      <span>{{ error }}</span><button type="button" @click="start">{{ t('重试') }}</button>
    </div>
    <iframe v-else :key="generation" ref="frame" :src="inlineVisualizationRuntimeUrl()" sandbox="allow-scripts" referrerpolicy="no-referrer" :title="t('交互内容')" :style="{ height: `${height}px` }" />
    <details><summary>{{ t('查看代码') }}</summary><pre><code>{{ source }}</code></pre></details>
  </section>
</template>

<style scoped>
.inline-visualization { --text: var(--theme-main-text); color: var(--text); }
iframe { width: 100%; display: block; border: 0; background: var(--theme-main-soft-background); border-radius: var(--radius); }
summary { padding: var(--space-2) 0; color: color-mix(in srgb, var(--text) 65%, transparent); }
.inline-visualization-error { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-3); }
button { background: var(--theme-control-background); color: var(--theme-control-text); border: 0; border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); }
button:hover { filter: brightness(.94); }
</style>
