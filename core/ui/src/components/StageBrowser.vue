<template>
  <div class="stage-browser">
    <div class="stage-browser-bar">
      <input
        v-model="urlInput"
        class="stage-browser-url"
        type="text"
        placeholder="输入网址..."
        @keydown.enter="navigate"
      />
      <button type="button" class="stage-browser-btn" title="刷新" @click="reload">↻</button>
      <button type="button" class="stage-browser-btn" title="在新窗口打开" @click="openExternal">↗</button>
    </div>
    <div class="stage-browser-frame-wrap">
      <iframe
        ref="iframeEl"
        :src="currentUrl"
        class="stage-browser-frame"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
        @load="onLoad"
      />
      <div v-if="blocked" class="stage-browser-blocked">
        <div class="stage-browser-blocked-content">
          <p>该站点不允许内嵌预览</p>
          <button type="button" @click="openExternal">在新窗口打开 ↗</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { openExternalUrl } from '../helpers/openUrl'

const props = defineProps<{
  url: string
}>()

const urlInput = ref(props.url)
const currentUrl = ref(props.url)
const iframeEl = ref<HTMLIFrameElement | null>(null)
const blocked = ref(false)

watch(() => props.url, (val) => {
  urlInput.value = val
  currentUrl.value = val
  blocked.value = false
})

function normalizeUrl(input: string): string {
  const trimmed = input.trim()
  if (!trimmed) return ''
  if (/^https?:\/\//.test(trimmed)) return trimmed
  return `https://${trimmed}`
}

function navigate() {
  const normalized = normalizeUrl(urlInput.value)
  if (normalized) {
    currentUrl.value = normalized
    blocked.value = false
  }
}

function reload() {
  if (iframeEl.value) {
    iframeEl.value.src = currentUrl.value
  }
}

function openExternal() {
  if (currentUrl.value) {
    // Route to the OS default browser (Tauri) or a new tab (web) instead of
    // window.open(...,'_blank'), which would navigate/open a webview window.
    void openExternalUrl(currentUrl.value)
  }
}

function onLoad() {
  // Try to detect if the page blocked framing
  try {
    const doc = iframeEl.value?.contentDocument
    if (doc === null) {
      // Cross-origin and blocked
      blocked.value = true
    }
  } catch {
    // SecurityError means cross-origin — page loaded fine, just can't inspect
    blocked.value = false
  }
}
</script>

<style scoped>
.stage-browser {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: transparent;
}
.stage-browser-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(0,0,0,0.3);
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 8%, transparent);
}
.stage-browser-url {
  flex: 1;
  min-width: 0;
  padding: 5px 10px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 12%, transparent);
  border-radius: var(--radius-sm);
  background: rgba(0,0,0,0.3);
  color: var(--theme-main-text, #f2efeb);
  font-size: 13px;
  outline: none;
}
.stage-browser-url:focus { border-color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 30%, transparent); }
.stage-browser-btn {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 72%, transparent);
  cursor: pointer;
  font-size: 14px;
  display: grid;
  place-items: center;
}
.stage-browser-btn:hover { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-press), transparent); }
.stage-browser-frame-wrap {
  flex: 1;
  position: relative;
  min-width: 0;
}
.stage-browser-frame {
  width: 100%;
  height: 100%;
  border: 0;
  /* 空白网页内容底色，非界面表面层 */
  background: #fff;
}
.stage-browser-blocked {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,0.92);
}
.stage-browser-blocked-content {
  text-align: center;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 58%, transparent);
}
.stage-browser-blocked-content p { margin: 0 0 12px; font-size: 14px; }
.stage-browser-blocked-content button {
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 20%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 72%, transparent);
  padding: 6px 16px;
  cursor: pointer;
  font-size: 13px;
}
.stage-browser-blocked-content button:hover { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-press), transparent); }
</style>
