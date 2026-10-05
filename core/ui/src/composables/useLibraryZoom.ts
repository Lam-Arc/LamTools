/**
 * 资料库分区的 Ctrl+滚轮缩放。
 *
 * 资料、方案两个分区共用同一档缩放（同一个存储键）：按住 Ctrl 滚动即增减，
 * 范围 0.6–1.6、步进 0.1，记住上次的档位。缩放作用在整个分区上——
 * 标题、工具栏、页签和卡片墙一起变（像整页缩放），不是只缩卡片
 * （CSS `zoom: var(--library-zoom)` 落在分区根元素上）。
 */
import { ref, watch } from 'vue'

const ZOOM_STORAGE_KEY = 'lamtools.core.library.zoom'
const MIN_ZOOM = 0.6
const MAX_ZOOM = 1.6
const ZOOM_STEP = 0.1

function readStoredZoom(): number {
  try {
    const value = Number(window.localStorage.getItem(ZOOM_STORAGE_KEY))
    return Number.isFinite(value) && value >= MIN_ZOOM && value <= MAX_ZOOM ? value : 1
  } catch {
    return 1
  }
}

const zoom = ref(readStoredZoom())

watch(zoom, (value) => {
  try {
    window.localStorage.setItem(ZOOM_STORAGE_KEY, String(value))
  } catch { /* 无存储时仅当前会话生效 */ }
})

export function useLibraryZoom() {
  function onZoomWheel(event: WheelEvent): void {
    if (!event.ctrlKey) return
    event.preventDefault()
    const direction = event.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP
    const next = Math.round((zoom.value + direction) * 10) / 10
    zoom.value = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next))
  }

  return { zoom, onZoomWheel }
}
