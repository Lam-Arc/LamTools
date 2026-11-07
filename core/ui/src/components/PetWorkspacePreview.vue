<script setup lang="ts">
/**
 * 桌宠工作台内嵌物理预览。
 *
 * user:“现有 PetPreview 可内嵌到工作台，不再只能弹窗导入”+
 * “预览世界使用与真实桌宠相同物理内核和渲染适配”+
 * (这里直接创建隔离的 PetWorld，与正式桌宠同一套物理/瓦片/动作执行；
 *  但不创建 pet-overlay、不注册全局热键、不发送 Agent 请求。)
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { PetWorld } from '@/pet/engine/world.ts'
import type { PetRecordConfig } from '@/pet/config.ts'
import { hitboxWorldRect } from '@/pet/engine/sprite.ts'
import * as bridge from '@/pet/bridge.ts'

const props = defineProps<{ record: PetRecordConfig }>()

const WIDTH = 640
const HEIGHT = 380
const root = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const visible = ref(true)
const paused = ref(false)
const speed = ref(1)
const showHitboxes = ref(true)
const actionId = ref('idle')
const status = ref('')
const error = ref('')

let world: PetWorld | null = null
let raf = 0
let lastFrame = 0
let simNow = 0
let drag: { petId: string; pointerId: number } | null = null
const images = new Map<string, HTMLImageElement>()
const loading = new Set<string>()

const actionIds = computed(() => ['idle', ...Object.keys(props.record.actions).filter(id => id !== 'idle')])

async function loadImage(source: string): Promise<HTMLImageElement | null> {
  const key = `${props.record.packId || 'inline'}::${source}`
  const existing = images.get(key)
  if (existing) return existing
  if (loading.has(key)) return null
  loading.add(key)
  try {
    const url = props.record.packId
      ? await bridge.packAssetUrl(props.record.packId, source)
      : await bridge.importAssetUrl(source)
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image()
      element.onload = () => resolve(element)
      element.onerror = () => reject(new Error(`图片无法解码：${source}`))
      element.src = url
    })
    images.set(key, image)
    return image
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    return null
  } finally {
    loading.delete(key)
  }
}

async function preload(): Promise<void> {
  const sources = new Set<string>()
  for (const clip of Object.values(props.record.actions)) {
    if (!clip) continue
    if (clip.type === 'frames') clip.sources.forEach(source => sources.add(source))
    else if (clip.type === 'static' || clip.type === 'spritesheet') sources.add(clip.source)
  }
  await Promise.all([...sources].map(source => loadImage(source)))
}

function createWorld(): void {
  cleanupWorld()
  error.value = ''
  const created = new PetWorld({
    screen: { x: 0, y: 0, width: WIDTH, height: HEIGHT },
    quality: 'low',
    useL3: false,
    graphRebuildDelayMs: 0,
  })
  world = created
  // 一张悬浮平台 + 一段竖边，和正式桌面共用同一套瓦片化与物理。
  created.addUserSegments([
    { id: 'preview-platform', kind: 'platform', layer: 'user', x1: 80, y1: 300, x2: 560, y2: 300, oneWay: true },
    { id: 'preview-wall', kind: 'vertical', layer: 'user', x1: 600, y1: 120, x2: 600, y2: 300, ladder: true },
  ])
  created.addPet({
    id: props.record.id,
    name: props.record.name,
    packId: props.record.packId || undefined,
    scale: props.record.scale,
    facing: props.record.facing,
    radius: props.record.radius,
    physics: props.record.physics,
    behavior: props.record.behavior,
    hitboxes: props.record.hitboxes,
    actions: props.record.actions,
    spriteWidth: props.record.spriteWidth,
    spriteHeight: props.record.spriteHeight,
    visible: true,
  }, { x: 320, y: 100 })
  actionId.value = 'idle'
  simNow = performance.now()
  status.value = '预览沙盒：本地物理与渲染，不会出现在桌面上'
}

function cleanupWorld(): void {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
  world?.dispose()
  world = null
  drag = null
}

function draw(): void {
  const element = canvas.value
  const instance = world
  if (!element || !instance) return
  const context = element.getContext('2d')
  if (!context) return
  const ratio = window.devicePixelRatio || 1
  if (element.width !== WIDTH * ratio || element.height !== HEIGHT * ratio) {
    element.width = Math.round(WIDTH * ratio)
    element.height = Math.round(HEIGHT * ratio)
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, WIDTH, HEIGHT)
  // 背景与平台。
  const background = context.createLinearGradient(0, 0, 0, HEIGHT)
  background.addColorStop(0, '#1a2230')
  background.addColorStop(1, '#0c1118')
  context.fillStyle = background
  context.fillRect(0, 0, WIDTH, HEIGHT)
  context.fillStyle = 'rgba(255,255,255,0.06)'
  for (let x = 0; x < WIDTH; x += 32) context.fillRect(x, 0, 1, HEIGHT)
  for (let y = 0; y < HEIGHT; y += 32) context.fillRect(0, y, WIDTH, 1)
  for (const segment of instance.terrain.all()) {
    if (segment.layer === 'L1') continue
    context.strokeStyle = segment.layer === 'user' ? 'rgba(255, 170, 90, 0.9)' : 'rgba(100, 180, 255, 0.75)'
    context.lineWidth = 2
    context.beginPath()
    context.moveTo(segment.x1, segment.y1)
    context.lineTo(segment.x2, segment.y2)
    context.stroke()
  }

  for (const state of instance.renderStates()) {
    if (!state.visible) continue
    const pet = instance.get(state.id)
    if (!pet) continue
    const clip = state.clip
    if (clip?.type === 'blocky' || clip?.type === 'model') {
      context.fillStyle = 'rgba(180, 210, 255, 0.16)'
      context.strokeStyle = 'rgba(160, 200, 255, 0.7)'
      context.lineWidth = 1.5
      context.beginPath()
      context.roundRect(state.rect.x, state.rect.y, state.rect.width, state.rect.height, 8)
      context.fill()
      context.stroke()
      context.fillStyle = 'rgba(220, 235, 255, 0.9)'
      context.font = '12px system-ui, sans-serif'
      context.textAlign = 'center'
      context.fillText('3D 角色（桌面测试查看）', state.rect.x + state.rect.width / 2, state.rect.y + state.rect.height / 2)
      continue
    }
    const image = state.frame ? images.get(`${props.record.packId || 'inline'}::${state.frame.source}`) : undefined
    if (image && state.frame) {
      context.save()
      if (state.facing < 0) {
        context.translate(state.rect.x + state.rect.width, state.rect.y)
        context.scale(-1, 1)
      } else {
        context.translate(state.rect.x, state.rect.y)
      }
      context.drawImage(
        image,
        state.frame.sx,
        state.frame.sy,
        state.frame.sw,
        state.frame.sh,
        0,
        0,
        state.rect.width,
        state.rect.height,
      )
      context.restore()
    } else {
      context.fillStyle = 'rgba(140, 190, 255, 0.25)'
      context.strokeStyle = 'rgba(140, 190, 255, 0.8)'
      context.beginPath()
      context.roundRect(state.rect.x, state.rect.y, state.rect.width, state.rect.height, 8)
      context.fill()
      context.stroke()
    }
    if (showHitboxes.value) {
      context.strokeStyle = 'rgba(255, 120, 200, 0.95)'
      context.lineWidth = 1.5
      for (const hitbox of state.hitboxes) {
        if (!hitbox.enabled) continue
        const rect = hitboxWorldRect(hitbox, state.rect, state.facing)
        context.strokeRect(rect.x, rect.y, rect.width, rect.height)
      }
      context.strokeStyle = 'rgba(90, 220, 255, 0.85)'
      const box = pet.renderRect()
      context.strokeRect(box.x, box.y, box.width, box.height)
    }
  }
}

function startLoop(): void {
  if (!visible.value || raf || !world) return
  lastFrame = 0
  raf = requestAnimationFrame(frame)
}

function stopLoop(): void {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

function frame(now: number): void {
  if (!visible.value) {
    raf = 0
    return
  }
  raf = requestAnimationFrame(frame)
  const instance = world
  if (!instance) return
  const delta = Math.min(64, now - (lastFrame || now))
  lastFrame = now
  if (!paused.value) {
    simNow += delta * speed.value
    instance.tick(simNow, delta * speed.value, { x: -10_000, y: -10_000 })
  }
  draw()
}

function restart(): void {
  // 隐藏的 details 不创建世界，避免多个角色同时跑物理。
  if (!visible.value) return
  createWorld()
  lastFrame = 0
  simNow = performance.now()
  startLoop()
}

function stepOnce(): void {
  const instance = world
  if (!instance) return
  paused.value = true
  simNow += 16 * speed.value
  instance.tick(simNow, 16 * speed.value, { x: -10_000, y: -10_000 })
  draw()
}

function playAction(): void {
  const pet = world?.get(props.record.id)
  if (!pet) return
  const result = pet.playAction(actionId.value)
  status.value = result ? `正在播放：${actionId.value}` : `动作未绑定资源：${actionId.value}`
}

function toWorld(event: PointerEvent): { x: number; y: number } {
  const element = canvas.value
  if (!element) return { x: 0, y: 0 }
  const box = element.getBoundingClientRect()
  return {
    x: (event.clientX - box.left) * (WIDTH / Math.max(1, box.width)),
    y: (event.clientY - box.top) * (HEIGHT / Math.max(1, box.height)),
  }
}

function onPointerDown(event: PointerEvent): void {
  const instance = world
  if (!instance) return
  const point = toWorld(event)
  const hit = instance.hitTest(point)
  if (hit) {
    hit.pet.startDrag(point)
    drag = { petId: hit.pet.id, pointerId: event.pointerId }
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
    status.value = '抓住角色：拖动后松手，物理会继承速度'
  } else {
    const pet = instance.get(props.record.id)
    const result = pet?.setDestination(point, { tiles: instance.tileGrid, now: Date.now() })
    status.value = result === 'ok' ? '已设置寻路目标' : '这个位置无法到达'
  }
}

function onPointerMove(event: PointerEvent): void {
  if (!drag) return
  world?.get(drag.petId)?.updateDrag(toWorld(event))
}

function onPointerUp(): void {
  if (!drag) return
  world?.get(drag.petId)?.endDrag()
  drag = null
}

function onPointerCancel(): void {
  onPointerUp()
}

let visibilityObserver: IntersectionObserver | null = null

function onWindowPointerUp(): void {
  if (drag) onPointerUp()
}

onMounted(() => {
  window.addEventListener('pointerup', onWindowPointerUp)
  window.addEventListener('pointercancel', onWindowPointerUp)
  if (typeof IntersectionObserver !== 'undefined' && root.value) {
    visibilityObserver = new IntersectionObserver(entries => {
      visible.value = Boolean(entries[0]?.isIntersecting)
      if (visible.value) {
        if (!world) {
          void preload().then(() => {
            void nextTick(() => restart())
          })
        } else {
          startLoop()
        }
      } else {
        stopLoop()
      }
    })
    visibilityObserver.observe(root.value)
  }
  void preload().then(() => {
    void nextTick(() => {
      restart()
    })
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('pointerup', onWindowPointerUp)
  window.removeEventListener('pointercancel', onWindowPointerUp)
  visibilityObserver?.disconnect()
  visibilityObserver = null
  cleanupWorld()
})

watch(() => props.record, () => {
  cleanupWorld()
  void preload().then(() => {
    void nextTick(() => {
      restart()
    })
  })
})
</script>

<template>
  <section ref="root" class="pet-workspace-preview">
    <header>
      <div>
        <strong>物理预览</strong>
        <span>{{ status }}</span>
      </div>
      <div class="pet-workspace-preview__actions">
        <select v-model="actionId" @change="playAction">
          <option v-for="id in actionIds" :key="id" :value="id">{{ id }}</option>
        </select>
        <button type="button" @click="paused = !paused">{{ paused ? '继续' : '暂停' }}</button>
        <button type="button" :disabled="!paused" @click="stepOnce">单步</button>
        <select v-model.number="speed" aria-label="预览速度">
          <option :value="0.5">0.5×</option>
          <option :value="1">1×</option>
          <option :value="2">2×</option>
        </select>
        <button type="button" @click="restart">重置</button>
        <label><input v-model="showHitboxes" type="checkbox"> 判定框</label>
      </div>
    </header>
    <canvas
      ref="canvas"
      class="pet-workspace-preview__canvas"
      :style="{ aspectRatio: `${WIDTH} / ${HEIGHT}` }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @pointerleave="onPointerMove"
    />
    <p v-if="error" class="pet-workspace-preview__error">{{ error }}</p>
    <p class="pet-workspace-preview__hint">
      点击空白处设置寻路目标；拖动角色后松手会保留速度。预览只在本组件内运行。
    </p>
  </section>
</template>

<style scoped>
.pet-workspace-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel, var(--surface, transparent));
}
.pet-workspace-preview header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
}
.pet-workspace-preview header span { margin-left: 8px; color: var(--muted); font-size: 11px; }
.pet-workspace-preview__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 11px;
}
.pet-workspace-preview__actions select,
.pet-workspace-preview__actions button {
  padding: 3px 7px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
  font-size: 11px;
}
.pet-workspace-preview__actions label { display: inline-flex; align-items: center; gap: 3px; color: var(--muted); }
.pet-workspace-preview__canvas {
  width: 100%;
  max-height: 360px;
  border-radius: 7px;
  background: #0c1118;
  cursor: crosshair;
  touch-action: none;
}
.pet-workspace-preview__hint,
.pet-workspace-preview__error { margin: 0; font-size: 11px; }
.pet-workspace-preview__hint { color: var(--muted); }
.pet-workspace-preview__error { color: var(--danger, #c0392b); }
</style>
