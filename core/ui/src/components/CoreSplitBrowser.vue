<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { ArrowLeft, ArrowRight, ExternalLink, Globe, RotateCw } from 'lucide-vue-next'
import { browserNative, hasSplitNative } from '@/split/native'
import { hostBlockedByOverlay, obscuresHostNode } from '@/split/browserOverlay'
import { openExternalUrl } from '@/helpers/openUrl'
import { contextMenuState } from './context-menu/context-menu'
import type { SplitTab } from '@/split/layout'
const props = defineProps<{ tab: SplitTab; visible: boolean }>()
const address = ref(props.tab.resource), host = ref<HTMLElement | null>(null), error = ref(''), loading = ref(false), created = ref(false)
let resizeObserver: ResizeObserver | undefined, classObserver: MutationObserver | undefined, childObserver: MutationObserver | undefined, unlisten: UnlistenFn | undefined, disposed = false, creating = false
let syncing = false, needsSync = false, lastBounds = ''
let syncFrame = 0
function queueSync() { if (!syncFrame) syncFrame = requestAnimationFrame(() => { syncFrame = 0; void sync() }) }
function url(raw: string) { const value = /^[a-z]+:/i.test(raw) ? raw : `https://${raw}`; const parsed = new URL(value); if (!['http:','https:'].includes(parsed.protocol)) throw Error('仅支持 HTTP 或 HTTPS 网页'); return parsed.href }
function options() { const r = host.value?.getBoundingClientRect(); return { x: Math.max(0, r?.x || 0), y: Math.max(0, r?.y || 0), width: r?.width || 1, height: r?.height || 1, visible: props.visible && !contextMenuState.open && !document.body.classList.contains('split-is-dragging') && !document.body.classList.contains('split-is-resizing') && !document.body.classList.contains('split-is-pulling') && !hostBlockedByOverlay(host.value) } }
async function sync() {
  if (!created.value || disposed) return
  if (syncing) { needsSync = true; return }
  const next = options(), serialized = JSON.stringify(next)
  if (serialized === lastBounds) return
  syncing = true
  try { await browserNative(props.tab.id, 'bounds', next); lastBounds = serialized }
  catch (e) { if (!disposed) error.value = String(e) }
  finally { syncing = false; if (needsSync) { needsSync = false; void sync() } }
}
async function navigate() {
  if (creating) return
  try {
    const target = url(address.value.trim()); error.value = ''; loading.value = true
    if (!hasSplitNative()) throw Error('内置浏览器需要在桌面应用中使用；也可以在默认浏览器中打开')
    creating = true
    await browserNative(props.tab.id, created.value ? 'navigate' : 'create', { ...options(), url: target })
    created.value = true; props.tab.resource = target; address.value = target; props.tab.title = new URL(target).hostname
    if (disposed) await browserNative(props.tab.id, 'close')
  } catch (e) { error.value = String(e); loading.value = false } finally { creating = false }
}
async function action(action: string) { try { await browserNative(props.tab.id, action) } catch (e) { error.value = String(e) } }
// user:“审查分屏代码，并优化”+(地址不合法时留在原地提示，而不是在点击处理里抛出无人接收的异常)。
function openExternal() {
  try { if (address.value.trim()) void openExternalUrl(url(address.value.trim())) }
  catch (e) { error.value = String(e) }
}
// user:“审查分屏代码，并优化”+(恢复布局时先不创建原生网页，等标签真正可见再加载，避免后台标签各开一个子 WebView)。
async function ensureBrowser() {
  if (!props.visible || created.value || creating || disposed || !props.tab.resource || !hasSplitNative()) return
  await navigate()
}
watch(() => props.visible, visible => { if (visible) void nextTick(ensureBrowser); void nextTick(sync) })
watch(() => contextMenuState.open, sync)
onMounted(async () => {
  if (typeof ResizeObserver !== 'undefined') { resizeObserver = new ResizeObserver(queueSync); resizeObserver.observe(host.value!) }
  // user:“审查分屏代码，并优化”+(只观察会影响网页宿主的两类变化：body 自身的拖动/缩放类名，以及模态框、右栏或菜单的插入删除)。
  if (typeof MutationObserver !== 'undefined') {
    classObserver = new MutationObserver(queueSync); classObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] })
    childObserver = new MutationObserver(records => { if (records.some(record => [...record.addedNodes, ...record.removedNodes].some(obscuresHostNode))) queueSync() })
    childObserver.observe(document.body, { childList: true, subtree: true })
  }
  window.addEventListener('resize', queueSync)
  if (hasSplitNative()) {
    unlisten = await listen<{ id: string; url: string; loading: boolean }>('lamtools://split-browser', ({ payload }) => {
      if (payload.id !== props.tab.id) return
      address.value = payload.url; props.tab.resource = payload.url; loading.value = payload.loading
      try { props.tab.title = new URL(payload.url).hostname } catch { /* Keep the existing title for transient URLs. */ }
    })
    if (disposed) { unlisten(); return }
  }
  await ensureBrowser()
})
onBeforeUnmount(() => { disposed = true; cancelAnimationFrame(syncFrame); resizeObserver?.disconnect(); classObserver?.disconnect(); childObserver?.disconnect(); unlisten?.(); window.removeEventListener('resize', queueSync); if (created.value) void browserNative(props.tab.id, 'close').catch(() => {}) })
</script>
<template>
  <div class="split-browser">
    <form class="split-content-toolbar" @submit.prevent="navigate"><button class="split-icon-button" type="button" title="后退" aria-label="后退" :disabled="!created" @click="action('back')"><ArrowLeft :size="14" /></button><button class="split-icon-button" type="button" title="前进" aria-label="前进" :disabled="!created" @click="action('forward')"><ArrowRight :size="14" /></button><button class="split-icon-button" type="button" title="刷新" aria-label="刷新" :disabled="!created" @click="action('reload')"><RotateCw :size="14" :class="{ 'split-browser-loading': loading }" /></button><input v-model="address" type="text" aria-label="网页地址" placeholder="输入网址，按 Enter 打开" spellcheck="false" /><button class="split-icon-button" type="button" title="在默认浏览器打开" aria-label="在默认浏览器打开" @click="openExternal"><ExternalLink :size="14" /></button></form>
    <p v-if="error" class="split-content-error" role="alert">{{ error }}</p>
    <div ref="host" class="split-browser-host"><div v-if="!created" class="split-empty"><Globe :size="26" :stroke-width="1.2" /><span>在这里打开网页，继续手边的工作</span></div></div>
  </div>
</template>
