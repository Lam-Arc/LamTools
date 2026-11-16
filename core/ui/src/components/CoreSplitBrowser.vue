<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { ArrowLeft, ArrowRight, ExternalLink, Globe, RotateCw } from 'lucide-vue-next'
import { browserNative, hasSplitNative } from '@/split/native'
import { hostBlockedByOverlay, obscuresHostNode } from '@/split/browserOverlay'
import { openExternalUrl } from '@/helpers/openUrl'
import { contextMenuState } from './context-menu/context-menu'
import type { SplitTab } from '@/split/layout'
export interface SplitBrowserServices {
  available: () => boolean
  call: (id: string, action: string, options?: Record<string, unknown>) => Promise<void>
  subscribe: (callback: (event: { id: string; url: string; loading: boolean }) => void) => Promise<UnlistenFn>
  openExternal: (url: string) => Promise<void>
}
const props = defineProps<{ tab: SplitTab; visible: boolean; services?: SplitBrowserServices }>()
// user:“交互测试”+(可注入隔离浏览器服务；未提供时继续使用桌面原生接口)。
const services: SplitBrowserServices = props.services ?? {
  available: hasSplitNative,
  call: browserNative,
  subscribe: callback => listen<{ id: string; url: string; loading: boolean }>('lamtools://split-browser', ({ payload }) => callback(payload)),
  openExternal: async url => { if (!await openExternalUrl(url)) throw new Error('无法打开默认浏览器') },
}
const address = ref(props.tab.resource), host = ref<HTMLElement | null>(null), error = ref(''), loading = ref(false), created = ref(false)
let resizeObserver: ResizeObserver | undefined, classObserver: MutationObserver | undefined, childObserver: MutationObserver | undefined, unlisten: UnlistenFn | undefined, disposed = false, creating = false
let eventListenerFailed = false
let listenerReady: Promise<void> = Promise.resolve()
let eventRevision = 0
let closing = false
// user:“确保视觉、功能和交互不退化”+(关闭期间完成的导航不能重复关闭或改写已退出的标签)。
async function closeOnce() { if (closing) return; closing = true; await services.call(props.tab.id, 'close') }
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
  try { await services.call(props.tab.id, 'bounds', next); lastBounds = serialized }
  catch (e) { if (!disposed) error.value = String(e) }
  finally { syncing = false; if (needsSync) { needsSync = false; void sync() } }
}
async function navigate() {
  if (creating) return
  try {
    const target = url(address.value.trim()); error.value = ''; loading.value = true
    if (!services.available()) throw Error('内置浏览器需要在桌面应用中使用；也可以在默认浏览器中打开')
    // user:“确保视觉、功能和交互不退化”+(等事件监听就绪后再创建网页，关闭期间不再创建)。
    creating = true
    await listenerReady
    if (disposed) return
    if (eventListenerFailed) throw Error('浏览器事件监听不可用，请关闭后重新打开分屏')
    const before = eventRevision
    await services.call(props.tab.id, created.value ? 'navigate' : 'create', { ...options(), url: target })
    if (disposed) { await closeOnce(); return }
    created.value = true
    // user:“确保视觉、功能和交互不退化”+(原生浏览器先报告重定向时，不用旧请求地址覆盖它)。
    if (eventRevision === before) { props.tab.resource = target; address.value = target; props.tab.title = new URL(target).hostname }
  } catch (e) { error.value = String(e); loading.value = false } finally { creating = false }
}
async function action(action: string) { try { await services.call(props.tab.id, action) } catch (e) { error.value = String(e) } }
// user:“审查分屏代码，并优化”+(地址不合法时留在原地提示，而不是在点击处理里抛出无人接收的异常)。
async function openExternal() {
  try { if (address.value.trim()) await services.openExternal(url(address.value.trim())) }
  catch (e) { error.value = String(e) }
}
// user:“审查分屏代码，并优化”+(恢复布局时先不创建原生网页，等标签真正可见再加载，避免后台标签各开一个子 WebView)。
async function ensureBrowser() {
  if (!props.visible || created.value || creating || disposed || !props.tab.resource || !services.available()) return
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
  if (services.available()) {
    // user:“确保视觉、功能和交互不退化”+(监听失败时明确提示，避免无状态的浏览器或未处理异常)。
    listenerReady = services.subscribe(payload => {
        if (disposed || payload.id !== props.tab.id) return
        eventRevision++
        address.value = payload.url; props.tab.resource = payload.url; loading.value = payload.loading
        try { props.tab.title = new URL(payload.url).hostname } catch { /* Keep the existing title for transient URLs. */ }
      }).then(stop => { if (disposed) stop(); else unlisten = stop })
      .catch(cause => { eventListenerFailed = true; if (!disposed) error.value = String(cause) })
    await listenerReady
    if (disposed || eventListenerFailed) return
  }
  await ensureBrowser()
})
onBeforeUnmount(() => { disposed = true; cancelAnimationFrame(syncFrame); resizeObserver?.disconnect(); classObserver?.disconnect(); childObserver?.disconnect(); unlisten?.(); window.removeEventListener('resize', queueSync); if (created.value) void closeOnce().catch(() => {}) })
</script>
<template>
  <div class="split-browser">
    <form class="split-content-toolbar" @submit.prevent="navigate"><button class="split-icon-button" type="button" title="后退" aria-label="后退" :disabled="!created" @click="action('back')"><ArrowLeft :size="14" /></button><button class="split-icon-button" type="button" title="前进" aria-label="前进" :disabled="!created" @click="action('forward')"><ArrowRight :size="14" /></button><button class="split-icon-button" type="button" title="刷新" aria-label="刷新" :disabled="!created" @click="action('reload')"><RotateCw :size="14" :class="{ 'split-browser-loading': loading }" /></button><input v-model="address" type="text" aria-label="网页地址" placeholder="输入网址，按 Enter 打开" spellcheck="false" /><button class="split-icon-button" type="button" title="在默认浏览器打开" aria-label="在默认浏览器打开" @click="openExternal"><ExternalLink :size="14" /></button></form>
    <p v-if="error" class="split-content-error" role="alert">{{ error }}</p>
    <div ref="host" class="split-browser-host"><div v-if="!created" class="split-empty"><Globe :size="26" :stroke-width="1.2" /><span>在这里打开网页，继续手边的工作</span></div></div>
  </div>
</template>
