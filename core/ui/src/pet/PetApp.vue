<template>
  <main
    class="pet-window"
    :style="{ opacity: settings.opacity, width: `${petSize}px`, height: `${petSize}px`, '--pet-scale': settings.scale }"
    :class="[`pet-${petVariant}`, `pet-state-${overview.global_state}`]"
    aria-label="LamTools 桌宠"
    @contextmenu.prevent="openOverlay"
    @pointerdown="beginPointer"
    @pointermove="movePointer"
    @pointerup="endPointer"
    @pointercancel="cancelPointer"
    @dragstart.prevent
    @selectstart.prevent
  >
    <div class="pet-shadow" />
    <img
      v-if="spriteFrame || builtinSprite"
      class="pet-sprite"
      :class="`pet-sprite-state-${overview.global_state}`"
      :src="spriteFrame || builtinSprite"
      draggable="false"
      alt=""
      @error="onSpriteError"
    />
    <div v-else class="pet-character" aria-hidden="true">
      <div class="pet-ear pet-ear-left" />
      <div class="pet-ear pet-ear-right" />
      <div class="pet-face">
        <span class="pet-eye pet-eye-left" />
        <span class="pet-eye pet-eye-right" />
        <span class="pet-muzzle"><i /></span>
      </div>
      <div class="pet-body" />
      <div class="pet-tail" />
    </div>
    <span v-if="overview.global_state === 'waiting'" class="pet-badge">{{ overview.waiting_count }}</span>
    <span v-else-if="overview.global_state === 'error'" class="pet-badge pet-badge-error">!</span>
    <span
      v-if="overview.global_state === 'error' && overview.active_errors.length"
      class="pet-error-bubble"
      :title="String(overview.active_errors[0].message || overview.active_errors[0].error || '任务执行失败')"
    >{{ String(overview.active_errors[0].message || overview.active_errors[0].error || '任务执行失败') }}</span>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { emit, listen, type UnlistenFn } from '@tauri-apps/api/event'
import { availableMonitors, currentMonitor, getCurrentWindow, LogicalPosition, PhysicalPosition } from '@tauri-apps/api/window'
import { createPetClient, defaultPetSettings, normalizeOverview, type PetOverview, type PetPack, type PetSettings } from './petClient'
import catSprite from './assets/default-cat.png'
import foxSprite from './assets/default-fox.png'
import robotSprite from './assets/default-robot.png'

const overview = ref<PetOverview>(normalizeOverview(null))
const settings = reactive<PetSettings>(defaultPetSettings(null))
const packs = ref<PetPack[]>([])
const spriteFrame = ref('')
const spriteLoadFailed = ref(false)
const petApiBase = ref('/api/core')
const petVariant = computed(() => {
  const id = settings.selected_pet.toLowerCase()
  return id.includes('fox') ? 'fox' : id.includes('robot') ? 'robot' : 'cat'
})
const builtinSprite = computed(() => {
  if (settings.selected_pet === 'default-fox') return foxSprite
  if (settings.selected_pet === 'default-robot') return robotSprite
  if (settings.selected_pet === 'default-cat') return catSprite
  return ''
})
const petSize = computed(() => Math.round(180 * settings.scale))
type PetClient = Awaited<ReturnType<typeof createPetClient>>['client']
let client: PetClient | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let unlistenMoved: UnlistenFn | null = null
let unlistenScale: UnlistenFn | null = null
let unlistenSettings: UnlistenFn | null = null
let placementTimer: ReturnType<typeof setTimeout> | null = null
let spriteTimer: ReturnType<typeof setInterval> | null = null
let pointerStart: { x: number; y: number } | null = null
let pointerMoved = false
let dragOrigin: { screenX: number; screenY: number; x: number; y: number; scale: number } | null = null
let latestPointerScreen: { x: number; y: number } | null = null
let positionRequest: { x: number; y: number } | null = null
let dragFrame: number | null = null
let positioning = false
let dragPending = false
let rebasingDrag = false
let nativeDragActive = false
let nativeDragPending = false
let dragSession = 0
let pointerAnchor: { x: number; y: number } | null = null
let windowScaleFactor = 1
let mounted = false
let settingsHydrated = false
const seenWaitingIds = new Set<string>()
const seenErrorKeys = new Set<string>()

function handleOverview(value: PetOverview) {
  overview.value = value
  void refreshSprite()
  void maybeShowAttentionOverlay()
}

async function maybeShowAttentionOverlay() {
  if (!settingsHydrated || !settings.enabled) return
  const waitingIds = new Set(overview.value.pending_interactions.map(item => item.id))
  const errorKeys = new Set(overview.value.active_errors.map(item => `${String(item.thread_id || '')}:${String(item.message || item.error || '')}`))
  const hasNewWaiting = [...waitingIds].some(id => !seenWaitingIds.has(id))
  // Errors remain a compact Pet bubble and are opened by clicking the Pet;
  // only new waiting interactions actively open the overlay panel.
  errorKeys.forEach(key => seenErrorKeys.add(key))
  for (const key of [...seenErrorKeys]) if (!errorKeys.has(key)) seenErrorKeys.delete(key)
  if (!hasNewWaiting) return
  try {
    // Keep unseen attention pending while the main window is focused or the
    // overlay is still starting. It will then be shown when the user is away
    // from the main window, without losing a waiting request.
    if (await invoke<boolean>('is_main_window_focused')) return
    if (!await openOverlay()) return
    waitingIds.forEach(id => seenWaitingIds.add(id))
    for (const id of [...seenWaitingIds]) if (!waitingIds.has(id)) seenWaitingIds.delete(id)
  } catch {
    // The overlay can still be building during startup; the next projection
    // change or a user click will retry through openOverlay().
  }
}

async function connect() {
  client?.close()
  client = null
  try {
    const created = await createPetClient(handleOverview, state => {
      if (state === 'closed' || state === 'error') scheduleReconnect()
    })
    petApiBase.value = created.rawBase
    client = created.client
    await client.connect()
    const response = await client.request('pet.overview.read')
    overview.value = normalizeOverview(response.overview)
    const settingResponse = await client.request('settings.get', { namespace: 'core.pet' })
    Object.assign(settings, defaultPetSettings(settingResponse.value))
    settingsHydrated = true
    const packResponse = await client.request('pet.packs.list')
    packs.value = Array.isArray(packResponse.packs) ? packResponse.packs as PetPack[] : []
    const selectedPack = packs.value.find(item => item.id === settings.selected_pet && item.valid)
    if (!selectedPack) {
      const fallback = packs.value.find(item => item.id === 'default-cat' && item.valid)
        || packs.value.find(item => item.valid)
      if (fallback) {
        settings.selected_pet = fallback.id
        await saveSettings()
      }
    }
    await refreshSprite()
    await applyNativeSize()
    await restorePlacement()
    if (!unlistenScale) {
      windowScaleFactor = await getCurrentWindow().scaleFactor()
      unlistenScale = await getCurrentWindow().onScaleChanged(({ payload }) => {
        windowScaleFactor = payload.scaleFactor || 1
        if (dragOrigin && (pointerStart || dragPending)) void rebaseDrag()
      })
    }
    await invoke(settings.enabled ? 'show_pet_window' : 'hide_pet_window')
    await emit('pet-visibility-changed', { enabled: settings.enabled })
    await maybeShowAttentionOverlay()
    if (!unlistenMoved) {
      unlistenMoved = await getCurrentWindow().onMoved(({ payload }) => {
        void currentMonitor().then(monitor => {
          const scaleFactor = monitor?.scaleFactor || 1
          settings.placement = {
            ...settings.placement,
            monitor: monitorKey(monitor),
            // Tauri emits PhysicalPosition for onMoved. Persist logical
            // coordinates so a different DPI monitor can restore safely.
            x: payload.x / scaleFactor,
            y: payload.y / scaleFactor,
          }
        }).catch(() => {
          return getCurrentWindow().scaleFactor().then(scaleFactor => {
            settings.placement = {
              ...settings.placement,
              x: payload.x / (scaleFactor || 1),
              y: payload.y / (scaleFactor || 1),
            }
          })
        }).finally(() => {
          if (placementTimer) clearTimeout(placementTimer)
          placementTimer = setTimeout(() => { void saveSettings() }, 250)
        })
      })
    }
  } catch {
    scheduleReconnect()
  }
}

function monitorKey(monitor: Awaited<ReturnType<typeof currentMonitor>>): string {
  if (!monitor) return ''
  return monitor.name || `${monitor.position.x}:${monitor.position.y}:${monitor.size.width}x${monitor.size.height}`
}

function logicalWorkArea(monitor: Awaited<ReturnType<typeof availableMonitors>>[number]) {
  const position = monitor.workArea.position.toLogical(monitor.scaleFactor)
  const size = monitor.workArea.size.toLogical(monitor.scaleFactor)
  return { x: position.x, y: position.y, width: size.width, height: size.height }
}

async function restorePlacement() {
  const placement = settings.placement
  if (placement?.x == null || placement?.y == null) return
  try {
    const monitors = await availableMonitors()
    if (!monitors.length) return
    const bounds = monitors.map(monitor => ({ monitor, area: logicalWorkArea(monitor) }))
    const monitor = monitors.find(item => monitorKey(item) === placement.monitor)
      || bounds.find(({ area }) => placement.x! >= area.x
        && placement.x! < area.x + area.width
        && placement.y! >= area.y
        && placement.y! < area.y + area.height)?.monitor
      || monitors[0]
    const area = logicalWorkArea(monitor)
    const x = Math.max(area.x, Math.min(
      placement.x,
      area.x + area.width - petSize.value,
    ))
    const y = Math.max(area.y, Math.min(
      placement.y,
      area.y + area.height - petSize.value,
    ))
    await getCurrentWindow().setPosition(new LogicalPosition(x, y))
    settings.placement = { ...placement, monitor: monitorKey(monitor), x, y }
  } catch {
    // A monitor can disappear between enumeration and placement. The native
    // window keeps its safe startup position in that case.
  }
}

async function applyNativeSize() {
  await invoke('resize_pet_window', { width: petSize.value, height: petSize.value })
}

async function refreshSprite() {
  if (spriteTimer) clearInterval(spriteTimer)
  spriteTimer = null
  spriteFrame.value = ''
  spriteLoadFailed.value = false
  const pack = packs.value.find(item => item.id === settings.selected_pet && item.valid)
  if (!pack) return
  const animation = pack.states[overview.value.global_state] || pack.states.idle
  if (!animation?.frames?.length) return
  let index = 0
  const update = () => {
    const path = animation.frames[index % animation.frames.length]
    const filename = path?.replaceAll('\\', '/').split('/').pop() || ''
    spriteFrame.value = filename
      ? `${petApiBase.value}/pets/${encodeURIComponent(pack.id)}/${encodeURIComponent(overview.value.global_state)}/${encodeURIComponent(filename)}`
      : ''
    index += 1
  }
  update()
  spriteTimer = setInterval(update, Math.max(16, 1000 / Math.max(1, animation.fps)))
}

async function saveSettings() {
  if (!client) return
  try {
    await client.request('settings.update', { namespace: 'core.pet', value: { ...settings } })
  } catch {
    // Position saves can race a reconnect/HMR close. The next connection
    // reads the persisted value; never surface an unhandled Vue rejection.
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (!mounted || reconnectTimer) return
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    void connect()
  }, 2000)
}

function focusMain() {
  void invoke('focus_main_window')
}

function onSpriteError() {
  spriteLoadFailed.value = true
  spriteFrame.value = ''
  if (spriteTimer) clearInterval(spriteTimer)
  spriteTimer = null
}

async function openOverlay(): Promise<boolean> {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      await invoke('show_pet_overlay')
      return true
    } catch {
      // Window creation is asynchronous during WebView2 startup. Recover from
      // a right-click that arrives before the overlay has finished building.
      if (attempt === 0) await invoke('ensure_pet_windows')
      await new Promise(resolve => setTimeout(resolve, 250))
    }
  }
  return false
}

function schedulePositionFlush() {
  if (dragFrame !== null || positioning) return
  dragFrame = requestAnimationFrame(() => {
    dragFrame = null
    if (positioning) return
    positioning = true
    void (async () => {
      try {
        while (positionRequest) {
          const next = positionRequest
          positionRequest = null
          try {
            // PhysicalPosition requires integer device pixels. Rounding here
            // also prevents fractional DPI values from being rejected by the
            // Tauri command, which previously made the Pet stop mid-drag.
            await getCurrentWindow().setPosition(new PhysicalPosition(
              Math.round(next.x),
              Math.round(next.y),
            ))
          } catch {
            // A closing/reloading WebView can invalidate one in-flight move;
            // keep the drag loop alive for the newest request when possible.
          }
        }
      } finally {
        positioning = false
        if (positionRequest) schedulePositionFlush()
      }
    })()
  })
}

function queuePosition(screenX: number, screenY: number) {
  if (!dragOrigin) return
  positionRequest = {
    x: dragOrigin.x + (screenX - dragOrigin.screenX) * dragOrigin.scale,
    y: dragOrigin.y + (screenY - dragOrigin.screenY) * dragOrigin.scale,
  }
  schedulePositionFlush()
}

async function rebaseDrag() {
  if (!dragOrigin || rebasingDrag || !latestPointerScreen) return
  rebasingDrag = true
  try {
    const position = await getCurrentWindow().outerPosition()
    if (!latestPointerScreen) return
    dragOrigin = {
      screenX: latestPointerScreen.x,
      screenY: latestPointerScreen.y,
      x: position.x,
      y: position.y,
      scale: windowScaleFactor || 1,
    }
    queuePosition(latestPointerScreen.x, latestPointerScreen.y)
  } catch {
    // Keep the previous scale until the next move can be rebased.
  } finally {
    rebasingDrag = false
  }
}

function startNativeDrag(session: number) {
  if (nativeDragActive || nativeDragPending || !pointerAnchor) return
  nativeDragPending = true
  const anchor = { ...pointerAnchor }
  void invoke('start_pet_drag', {
    anchor_x: anchor.x,
    anchor_y: anchor.y,
  }).then(() => {
    nativeDragPending = false
    if (session !== dragSession || !pointerStart) {
      void invoke('stop_pet_drag').catch(() => undefined)
      return
    }
    nativeDragActive = true
  }).catch(() => {
    nativeDragPending = false
    if (session === dragSession && pointerMoved && dragOrigin && latestPointerScreen) {
      queuePosition(latestPointerScreen.x, latestPointerScreen.y)
    }
  })
}

function beginPointer(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)
  dragSession += 1
  nativeDragActive = false
  nativeDragPending = false
  void invoke('stop_pet_drag').catch(() => undefined)
  if (dragFrame !== null) cancelAnimationFrame(dragFrame)
  dragFrame = null
  pointerStart = { x: event.clientX, y: event.clientY }
  pointerAnchor = { x: event.clientX, y: event.clientY }
  pointerMoved = false
  dragOrigin = null
  latestPointerScreen = { x: event.screenX, y: event.screenY }
  positionRequest = null
  dragPending = false
  void (async () => {
    try {
      const window = getCurrentWindow()
      const [position, scale] = await Promise.all([window.outerPosition(), window.scaleFactor()])
      windowScaleFactor = scale || 1
      dragOrigin = {
        screenX: event.screenX,
        screenY: event.screenY,
        x: position.x,
        y: position.y,
        scale: windowScaleFactor,
      }
      if (latestPointerScreen && (pointerMoved || dragPending)) {
        queuePosition(latestPointerScreen.x, latestPointerScreen.y)
        dragPending = false
      }
    } catch {
      dragOrigin = null
    }
  })()
}

function movePointer(event: PointerEvent) {
  if (!pointerStart) return
  event.preventDefault()
  latestPointerScreen = { x: event.screenX, y: event.screenY }
  const distance = Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y)
  if (distance >= 6 && !pointerMoved) {
    pointerMoved = true
    dragPending = true
    startNativeDrag(dragSession)
  }
  if (nativeDragActive || nativeDragPending) return
  if (!pointerMoved || !dragOrigin) return
  if (dragOrigin.scale !== windowScaleFactor) {
    void rebaseDrag()
    return
  }
  queuePosition(event.screenX, event.screenY)
}

function endPointer(event: PointerEvent) {
  event.preventDefault()
  const wasDragged = pointerMoved || dragPending
  const usedNativeDrag = nativeDragActive || nativeDragPending
  const target = event.currentTarget as HTMLElement
  if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId)
  dragSession += 1
  void invoke('stop_pet_drag').catch(() => undefined)
  nativeDragActive = false
  nativeDragPending = false
  if (pointerStart && !pointerMoved && !dragPending) {
    if (overview.value.waiting_count > 0) void openOverlay()
    else focusMain()
  }
  pointerStart = null
  pointerMoved = false
  pointerAnchor = null
  if (!wasDragged) {
    dragOrigin = null
    latestPointerScreen = null
    positionRequest = null
    if (dragFrame !== null) cancelAnimationFrame(dragFrame)
    dragFrame = null
    dragPending = false
  } else if (!usedNativeDrag) {
    dragPending = true
    if (latestPointerScreen) queuePosition(latestPointerScreen.x, latestPointerScreen.y)
  }
  if (usedNativeDrag) {
    dragOrigin = null
    latestPointerScreen = null
    positionRequest = null
  }
  dragPending = false
}

function cancelPointer(event: PointerEvent) {
  const target = event.currentTarget as HTMLElement
  if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId)
  dragSession += 1
  void invoke('stop_pet_drag').catch(() => undefined)
  nativeDragActive = false
  nativeDragPending = false
  pointerStart = null
  pointerMoved = false
  pointerAnchor = null
  dragOrigin = null
  latestPointerScreen = null
  positionRequest = null
  dragPending = false
  if (dragFrame !== null) cancelAnimationFrame(dragFrame)
  dragFrame = null
}

onMounted(async () => {
  mounted = true
  unlistenSettings = await listen<PetSettings>('pet-settings-changed', ({ payload }) => {
    Object.assign(settings, defaultPetSettings(payload))
    settingsHydrated = true
    void applyNativeSize()
    void refreshSprite()
    void maybeShowAttentionOverlay()
  })
  void connect()
})
onBeforeUnmount(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (placementTimer) clearTimeout(placementTimer)
  if (spriteTimer) clearInterval(spriteTimer)
  mounted = false
  void invoke('stop_pet_drag').catch(() => undefined)
  unlistenMoved?.()
  unlistenScale?.()
  unlistenSettings?.()
  client?.close()
})
</script>

<style>
html, body, #app { width: 100%; height: 100%; margin: 0; overflow: hidden; background: transparent; user-select: none; -webkit-user-select: none; }
body { margin: 0; }
.pet-window { position: relative; width: 180px; height: 180px; cursor: grab; user-select: none; -webkit-user-select: none; -webkit-user-drag: none; transform-origin: center bottom; }
.pet-window:active { cursor: grabbing; }
.pet-sprite { position: absolute; left: 50%; top: 50%; width: 144px; height: 156px; object-fit: contain; transform: translate(-50%, -50%) scale(var(--pet-scale, 1)); transform-origin: center; image-rendering: auto; -webkit-user-drag: none; animation: pet-float 2.4s ease-in-out infinite; }
.pet-sprite-state-running { animation-duration: .85s; }
.pet-sprite-state-waiting { animation-duration: 1.1s; }
.pet-sprite-state-error { animation: pet-shake .45s ease-in-out infinite alternate; }
.pet-character { position: absolute; left: 50%; top: 50%; width: 96px; height: 125px; transform: translate(-50%, -50%) scale(var(--pet-scale, 1)); transform-origin: center; animation: pet-float 2.4s ease-in-out infinite; }
.pet-face { position: absolute; z-index: 2; left: 10px; top: 10px; width: 76px; height: 70px; border-radius: 48% 48% 44% 44%; background: linear-gradient(145deg, #ffc878, #ed8d43); border: 3px solid #6e3d2a; }
.pet-ear { position: absolute; z-index: 1; top: 0; width: 34px; height: 42px; background: #ed9a4c; border: 3px solid #6e3d2a; transform: rotate(35deg); }
.pet-ear-left { left: 5px; border-radius: 8px 30px 8px 30px; }
.pet-ear-right { right: 5px; transform: rotate(55deg); border-radius: 30px 8px 30px 8px; }
.pet-eye { position: absolute; top: 28px; width: 10px; height: 13px; border-radius: 50%; background: #34231d; animation: pet-blink 4.8s infinite; }
.pet-eye-left { left: 19px; }.pet-eye-right { right: 19px; }
.pet-muzzle { position: absolute; left: 27px; bottom: 10px; width: 21px; height: 15px; border-radius: 50%; background: #ffe4ba; }
.pet-muzzle i { position: absolute; left: 8px; top: 3px; width: 6px; height: 5px; border-radius: 50%; background: #6e3d2a; }
.pet-body { position: absolute; z-index: 1; left: 17px; top: 69px; width: 62px; height: 57px; border-radius: 45% 45% 35% 35%; background: #f2a254; border: 3px solid #6e3d2a; }
.pet-tail { position: absolute; z-index: 0; right: 0; top: 84px; width: 34px; height: 45px; border: 9px solid #ed974c; border-left-color: transparent; border-bottom-color: transparent; border-radius: 50%; transform: rotate(18deg); }
.pet-shadow { position: absolute; left: 50%; bottom: 17px; width: 105px; height: 18px; border-radius: 50%; background: rgba(0,0,0,.22); filter: blur(5px); transform: translateX(-50%) scale(var(--pet-scale, 1)); transform-origin: center; }
.pet-badge { position: absolute; right: 13px; top: 14px; min-width: 24px; height: 24px; padding: 0 6px; border-radius: 14px; background: #e7a23b; color: #2f201b; font: 700 14px/24px system-ui; text-align: center; box-shadow: 0 3px 10px rgba(0,0,0,.3); transform: scale(var(--pet-scale, 1)); transform-origin: right top; }
.pet-badge-error { background: #e65e55; color: white; }
.pet-error-bubble { position: absolute; left: 100%; top: 18px; max-width: 210px; padding: 7px 10px; border-radius: 10px; background: rgba(44, 30, 31, .94); color: #fff2ed; font: 12px/1.35 system-ui; box-shadow: 0 4px 14px rgba(0,0,0,.28); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none; }
.pet-fox .pet-face, .pet-fox .pet-body { background: linear-gradient(145deg, #ffb15c, #d9653c); }
.pet-fox .pet-ear { background: #d9653c; }
.pet-robot .pet-face, .pet-robot .pet-body { background: linear-gradient(145deg, #8bd2dd, #568ca3); }
.pet-robot .pet-ear { background: #568ca3; border-radius: 8px; transform: rotate(0); }
.pet-robot .pet-eye { background: #e8ffff; box-shadow: 0 0 6px #e8ffff; }
.pet-state-running .pet-character { animation-duration: .85s; }
.pet-state-waiting .pet-character { animation-duration: 1.1s; }
.pet-state-error .pet-character { animation: pet-shake .45s ease-in-out infinite alternate; }
@keyframes pet-float { 0%,100% { transform: translate(-50%, -50%) scale(var(--pet-scale, 1)); } 50% { transform: translate(-50%, calc(-50% - 8px)) scale(var(--pet-scale, 1)); } }
@keyframes pet-blink { 0%, 45%, 49%, 100% { transform: scaleY(1); } 47% { transform: scaleY(.1); } }
@keyframes pet-shake { from { transform: translate(-50%, -50%) scale(var(--pet-scale, 1)) rotate(-3deg); } to { transform: translate(-50%, -50%) scale(var(--pet-scale, 1)) rotate(3deg); } }
@media (prefers-reduced-motion: reduce) {
  .pet-sprite, .pet-character, .pet-eye { animation: none !important; }
}
</style>
