<script setup lang="ts">
/**
 * 导入预览器（也是角色调试器）。
 *
 * user:“预览内模拟桌面复用正式运行时的物理、寻路、动作和行为逻辑，不用另一套假规则”+
 * “内置测试图符合外回形 + 内左竖边接地 + 内右标准半圆 + 外上缘断口”+
 * (确认添加后才创建真实桌面实例；取消不留残留。)
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { PetWorld } from '../engine/world.ts'
import { buildTestArena } from '../engine/terrain.ts'
import { createDefaultSettings } from '../engine/pet.ts'
import type { PetHitbox } from '../engine/sprite.ts'
import { clipPrimarySource, defaultHitboxes } from '../engine/sprite.ts'
import type { RenderablePet } from '../render/types.ts'
import { createThreePetLayer, type ThreePetLayer } from '../render/threeLayer.ts'
import * as bridge from '../bridge.ts'
import type { PetRuntime } from './usePetRuntime.ts'

const props = defineProps<{ runtime: PetRuntime }>()

const canvas = ref<HTMLCanvasElement | null>(null)
const glCanvas = ref<HTMLCanvasElement | null>(null)
const three = shallowRef<ThreePetLayer | null>(null)
const threeError = ref('')
const threeInfo = ref('')
const world = shallowRef<PetWorld | null>(null)
const petId = 'preview'
const running = ref(true)
const actionList = ['idle', 'walk', 'jump', 'jump_happy', 'climb', 'hang', 'fall', 'dance', 'interact', 'rest']
const selectedAction = ref('idle')
const mode = ref<'free' | 'action' | 'target' | 'hitbox'>('free')
/** Hitbox 可视化编辑：归一化坐标存在这里，确认时写进角色记录。 */
const hitboxes = ref<PetHitbox[]>(defaultHitboxes())
const selectedHitbox = ref(0)
const hitboxDrag = ref<{
  index: number
  action: 'move' | 'resize'
  startX: number
  startY: number
  origin: { x: number; y: number; width: number; height: number }
} | null>(null)
const debug = ref({ terrain: true, colliders: false, path: false, velocity: false })
const lastMessage = ref('')
const confirmError = ref('')
const busy = ref(false)
let raf = 0
let lastAt = 0
const WIDTH = 760
const HEIGHT = 520

const analysis = computed(() => props.runtime.importer.analysis)

onMounted(async () => {
  await setupWorld()
  await setupThree()
  raf = requestAnimationFrame(loop)
})

onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf)
})

watch(() => props.runtime.importer.analysis, () => { void setupWorld() })

/** 预览器同样走真实渲染层：3D 角色在这里就能看到。 */
async function setupThree(): Promise<void> {
  if (!glCanvas.value || three.value) return
  const layer = await createThreePetLayer({
    canvas: glCanvas.value,
    overlay: { x: 0, y: 0, width: WIDTH, height: HEIGHT },
    loadBytes: (_packId, source) => bridge.readImportAsset(source),
    onError: (scope, message) => { threeError.value = `${scope}: ${message}` },
  })
  if (!layer) {
    threeError.value = 'WebGL 不可用，3D 角色只能显示占位'
    return
  }
  layer.resize({ x: 0, y: 0, width: WIDTH, height: HEIGHT }, WIDTH, HEIGHT)
  three.value = layer
  void refreshThreeInfo()
}

async function refreshThreeInfo(): Promise<void> {
  const analysisValue = props.runtime.importer.analysis
  const model = analysisValue ? Object.values(analysisValue.actions).find(clip => clip?.type === 'model') : undefined
  if (!model || model.type !== 'model' || !three.value) return
  const result = await three.value.loadModel({ packId: null, source: model.source })
  threeInfo.value = result.ok
    ? `模型已加载：${result.animations.length} 段动画，${result.triangles} 个三角面`
    : `模型加载失败：${result.error || '未知原因'}`
}

async function setupWorld(): Promise<void> {
  const analysisValue = props.runtime.importer.analysis
  if (!analysisValue) return
  const created = new PetWorld({
    screen: { x: 0, y: 0, width: WIDTH, height: HEIGHT },
    quality: props.runtime.config.quality,
    useL3: false,
    graphRebuildDelayMs: 0,
  })
  created.addUserSegments(buildTestArena(WIDTH, HEIGHT, 26))
  const settings = createDefaultSettings(petId, analysisValue.name)
  settings.actions = analysisValue.actions
  settings.spriteWidth = props.runtime.importer.spriteWidth
  settings.spriteHeight = props.runtime.importer.spriteHeight
  settings.radius = Math.max(10, Math.round(Math.min(settings.spriteWidth, settings.spriteHeight) * 0.38))
  settings.scale = props.runtime.importer.scale
  created.addPet(settings, { x: WIDTH * 0.35, y: HEIGHT * 0.3 })
  world.value = created
  const manifestHitboxes = analysisValue.manifest.hitboxes
  hitboxes.value = Array.isArray(manifestHitboxes) && manifestHitboxes.length > 0
    ? manifestHitboxes.map(item => ({ ...item }))
    : defaultHitboxes()
  selectedHitbox.value = 0
  lastMessage.value = ''
  // 预载所有会用到的图片：预览和桌面用同一套资源读取。
  for (const clip of Object.values(analysisValue.actions)) {
    if (!clip) continue
    // 方块人不需要预载图片：皮肤由渲染层生成或单独加载。
    if (clip.type === 'blocky') continue
    if (clip.type === 'frames') {
      for (const source of clip.sources) await props.runtime.loadSpriteImage(null, source)
    } else {
      await props.runtime.loadSpriteImage(null, clip.source)
    }
  }
}

function loop(now: number): void {
  raf = requestAnimationFrame(loop)
  const instance = world.value
  if (!instance) return
  const delta = Math.min(64, now - (lastAt || now))
  lastAt = now
  if (running.value) {
    instance.tick(now, delta, null)
  }
  draw(instance, delta)
}

/** Hitbox 编辑叠层：只看精灵框，不受物理拖动干扰。 */
function drawHitboxEditor(context: CanvasRenderingContext2D, instance: PetWorld): void {
  const pet = instance.get(petId)
  if (!pet) return
  const rect = pet.renderRect()
  context.save()
  context.strokeStyle = 'rgba(255,255,255,0.35)'
  context.setLineDash([4, 4])
  context.strokeRect(rect.x, rect.y, rect.width, rect.height)
  context.setLineDash([])
  hitboxes.value.forEach((hitbox, index) => {
    const x = rect.x + hitbox.x * rect.width
    const y = rect.y + hitbox.y * rect.height
    const width = hitbox.width * rect.width
    const height = hitbox.height * rect.height
    const selected = index === selectedHitbox.value
    context.strokeStyle = hitbox.enabled
      ? (selected ? 'rgba(255,196,120,0.95)' : 'rgba(126,180,255,0.8)')
      : 'rgba(150,150,150,0.45)'
    context.lineWidth = selected ? 2.5 : 1.5
    context.strokeRect(x, y, width, height)
    context.fillStyle = hitbox.enabled
      ? (selected ? 'rgba(255,196,120,0.14)' : 'rgba(126,180,255,0.1)')
      : 'rgba(150,150,150,0.08)'
    context.fillRect(x, y, width, height)
    // 右下角缩放把手。
    context.fillStyle = 'rgba(255,255,255,0.9)'
    context.fillRect(x + width - 6, y + height - 6, 6, 6)
    context.fillStyle = 'rgba(240,246,255,0.9)'
    context.font = '11px system-ui, sans-serif'
    context.fillText(`${hitbox.name} → ${hitbox.action}`, x + 4, y + 13)
  })
  context.restore()
}

function draw(instance: PetWorld, delta = 16): void {
  const element = canvas.value
  if (!element) return
  element.width = WIDTH
  element.height = HEIGHT
  const context = element.getContext('2d')
  if (!context) return
  context.clearRect(0, 0, WIDTH, HEIGHT)
  context.fillStyle = '#11141a'
  context.fillRect(0, 0, WIDTH, HEIGHT)
  if (debug.value.terrain) {
    for (const segment of instance.terrain.all()) {
      // 与覆盖层同一套配色：黄=L1 屏幕边界，蓝=L2 窗口，绿=L3，粉=手绘。
      context.strokeStyle = segment.layer === 'L1'
        ? 'rgba(255,213,0,0.8)'
        : segment.layer === 'L2'
          ? 'rgba(80,170,255,0.9)'
          : segment.layer === 'L3'
            ? 'rgba(150,220,160,0.8)'
            : 'rgba(255,120,160,0.9)'
      context.lineWidth = 2
      context.beginPath()
      context.moveTo(segment.x1, segment.y1)
      context.lineTo(segment.x2, segment.y2)
      context.stroke()
    }
  }
  const renderables: RenderablePet[] = []
  for (const state of instance.renderStates()) {
    const pet = instance.get(state.id)
    const isModel = state.clip?.type === 'model'
    if (isModel && pet) {
      renderables.push({
        id: state.id,
        clip: state.clip,
        rect: state.rect,
        facing: state.facing,
        actionId: state.actionId || 'idle',
        elapsedMs: state.elapsedMs,
        visible: state.visible,
        packId: null,
      })
    }
    const sprite = state.frame && !isModel ? spriteFor(state.frame.source) : null
    const x = state.rect.x
    const y = state.rect.y
    if (sprite && state.frame) {
      context.save()
      if (state.facing < 0) {
        context.translate(x + state.rect.width, y)
        context.scale(-1, 1)
      } else {
        context.translate(x, y)
      }
      context.drawImage(sprite, state.frame.sx, state.frame.sy, state.frame.sw, state.frame.sh, 0, 0, state.rect.width, state.rect.height)
      context.restore()
    } else if (!isModel) {
      context.fillStyle = 'rgba(126,180,255,0.35)'
      context.fillRect(x, y, state.rect.width, state.rect.height)
    }
    if (debug.value.colliders && pet) {
      context.strokeStyle = 'rgba(90,220,255,0.9)'
      context.beginPath()
      const box = pet.renderRect()
      context.strokeRect(box.x, box.y, box.width, box.height)
      context.stroke()
    }
    if (debug.value.path && pet) {
      const path = pet.plannedTilePath
      if (path.length > 0) {
        context.strokeStyle = 'rgba(120,255,190,0.9)'
        context.setLineDash([5, 5])
        context.beginPath()
        context.moveTo(pet.position.x, pet.position.y)
        for (const cell of path) {
          const wp = instance.tileGrid.standPoint(cell.col, cell.row)
          context.lineTo(wp.x, wp.y)
        }
        context.stroke()
        context.setLineDash([])
      }
    }
    if (debug.value.velocity && pet) {
      context.strokeStyle = 'rgba(255,224,120,0.95)'
      context.beginPath()
      context.moveTo(pet.position.x, pet.position.y)
      context.lineTo(pet.position.x + pet.body.vx * 0.06, pet.position.y + pet.body.vy * 0.06)
      context.stroke()
    }
  }
  if (mode.value === 'hitbox') drawHitboxEditor(context, instance)
  const layer = three.value
  if (layer && renderables.length > 0) {
    layer.update(renderables, Math.min(64, delta))
    layer.render()
  }
}

const spriteCache = new Map<string, HTMLImageElement>()
function spriteFor(source: string): HTMLImageElement | null {
  return spriteCache.get(`import::${source}`) || null
}

/** 图片加载在运行时层，这里把结果同步进预览缓存。 */
async function hydrateSprites(): Promise<void> {
  const analysisValue = props.runtime.importer.analysis
  if (!analysisValue) return
  for (const clip of Object.values(analysisValue.actions)) {
    if (!clip) continue
    if (clip.type === 'blocky') continue
    const sources = clip.type === 'frames' ? clip.sources : [clip.source]
    for (const source of sources) {
      const image = await props.runtime.loadSpriteImage(null, source)
      if (image) spriteCache.set(`import::${source}`, image)
    }
  }
}
void hydrateSprites()

function pointer(event: PointerEvent): { x: number; y: number } {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  return {
    x: ((event.clientX - rect.left) / rect.width) * WIDTH,
    y: ((event.clientY - rect.top) / rect.height) * HEIGHT,
  }
}

function normalizedPoint(event: PointerEvent): { x: number; y: number; rect: { x: number; y: number; width: number; height: number } } | null {
  const pet = world.value?.get(petId)
  if (!pet) return null
  const rect = pet.renderRect()
  const point = pointer(event)
  return {
    x: (point.x - rect.x) / Math.max(1, rect.width),
    y: (point.y - rect.y) / Math.max(1, rect.height),
    rect,
  }
}

function onHitboxDown(event: PointerEvent): void {
  const position = normalizedPoint(event)
  if (!position) return
  // 先判缩放把手，再判移动：把手在角上，重叠时优先缩放。
  for (let index = hitboxes.value.length - 1; index >= 0; index -= 1) {
    const hitbox = hitboxes.value[index]
    const handleX = hitbox.x + hitbox.width
    const handleY = hitbox.y + hitbox.height
    const nearHandle = Math.abs(position.x - handleX) < 0.04 && Math.abs(position.y - handleY) < 0.04
    const inside = position.x >= hitbox.x && position.x <= handleX
      && position.y >= hitbox.y && position.y <= handleY
    if (!inside && !nearHandle) continue
    selectedHitbox.value = index
    hitboxDrag.value = {
      index,
      action: nearHandle ? 'resize' : 'move',
      startX: position.x,
      startY: position.y,
      origin: { x: hitbox.x, y: hitbox.y, width: hitbox.width, height: hitbox.height },
    }
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
    return
  }
}

function onHitboxMove(event: PointerEvent): void {
  const drag = hitboxDrag.value
  if (!drag) return
  const position = normalizedPoint(event)
  if (!position) return
  const hitbox = hitboxes.value[drag.index]
  if (!hitbox) return
  const clamp01 = (value: number) => Math.min(1, Math.max(0, value))
  if (drag.action === 'move') {
    hitbox.x = clamp01(drag.origin.x + (position.x - drag.startX))
    hitbox.y = clamp01(drag.origin.y + (position.y - drag.startY))
    hitbox.width = Math.min(drag.origin.width, 1 - hitbox.x)
    hitbox.height = Math.min(drag.origin.height, 1 - hitbox.y)
  } else {
    hitbox.width = clamp01(position.x) - hitbox.x
    hitbox.height = clamp01(position.y) - hitbox.y
    if (hitbox.width < 0.04) hitbox.width = 0.04
    if (hitbox.height < 0.04) hitbox.height = 0.04
  }
}

function onHitboxUp(): void {
  hitboxDrag.value = null
}

function onCanvasPointerDown(event: PointerEvent): void {
  if (mode.value === 'hitbox') {
    onHitboxDown(event)
    return
  }
  onCanvasClick(event)
}

function onCanvasClick(event: PointerEvent): void {
  const instance = world.value
  const pet = instance?.get(petId)
  if (!instance || !pet) return
  if (mode.value === 'hitbox') return
  const point = pointer(event)
  if (mode.value === 'target') {
    const result = pet.setDestination(point, { tiles: instance.tileGrid, now: Date.now() })
    lastMessage.value = result === 'ok'
      ? '规划成功：瓦片路标已生成，宠物正在按路标移动'
      : '目标不可达：已明确失败，没有制造假路径'
  }
}

function addHitbox(): void {
  const index = hitboxes.value.length
  hitboxes.value = [
    ...hitboxes.value,
    {
      id: `region-${Date.now().toString(36)}`,
      name: `区域${index + 1}`,
      x: 0.3,
      y: 0.2,
      width: 0.4,
      height: 0.3,
      action: 'interact',
      enabled: true,
    },
  ]
  selectedHitbox.value = hitboxes.value.length - 1
}

function removeHitbox(): void {
  if (hitboxes.value.length <= 1) {
    lastMessage.value = '至少要保留一个交互区域，否则角色无法点击'
    return
  }
  hitboxes.value = hitboxes.value.filter((_, index) => index !== selectedHitbox.value)
  selectedHitbox.value = Math.max(0, selectedHitbox.value - 1)
}

function updateSelectedHitbox(patch: Partial<PetHitbox>): void {
  const current = hitboxes.value[selectedHitbox.value]
  if (!current) return
  hitboxes.value = hitboxes.value.map((hitbox, index) => (
    index === selectedHitbox.value ? { ...hitbox, ...patch } : hitbox
  ))
}

function playAction(): void {
  const pet = world.value?.get(petId)
  if (!pet) return
  const reason = pet.playAction(selectedAction.value)
  lastMessage.value = `执行 ${selectedAction.value}：${reason}`
}

function stepOnce(): void {
  const instance = world.value
  if (!instance) return
  running.value = false
  instance.tick(performance.now(), 1000 / 60, null)
}

function reset(): void {
  void setupWorld()
}

async function confirm(): Promise<void> {
  busy.value = true
  confirmError.value = ''
  try {
    // 编辑过的 Hitbox 直接进角色记录：改点击范围不会动物理碰撞体。
  await props.runtime.confirmImport({ hitboxes: hitboxes.value })
  } catch (error) {
    confirmError.value = error instanceof Error ? error.message : String(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="preview" role="dialog" aria-label="角色预览器">
    <div class="preview__panel">
      <header class="preview__head">
        <strong>预览：{{ analysis?.name || '角色' }}</strong>
        <span class="preview__sub">先预览，确认后才添加到桌面</span>
        <button type="button" class="preview__close" @click="runtime.cancelImport()">✕</button>
      </header>

      <div class="preview__body">
        <div class="preview__stage">
          <div class="preview__stage-stack" :style="{ aspectRatio: `${WIDTH} / ${HEIGHT}` }">
            <canvas
              ref="canvas"
              class="preview__canvas"
              @pointerdown="onCanvasPointerDown"
              @pointermove="onHitboxMove"
              @pointerup="onHitboxUp"
              @pointercancel="onHitboxUp"
            />
            <canvas ref="glCanvas" class="preview__canvas preview__canvas--gl" aria-hidden="true" />
          </div>
          <div class="preview__hint-line">
            测试图：外回形 + 内左竖边接地 + 内右半圆 + 外上缘断口（尺寸随碰撞体自适应）
          </div>
        </div>

        <aside class="preview__side">
          <div class="preview__group">
            <div class="preview__label">测试模式</div>
            <div class="preview__row">
              <button type="button" :class="{ active: mode === 'free' }" @click="mode = 'free'">自由运行</button>
              <button type="button" :class="{ active: mode === 'action' }" @click="mode = 'action'">指定 Action</button>
              <button type="button" :class="{ active: mode === 'target' }" @click="mode = 'target'">点击设目标</button>
              <button type="button" :class="{ active: mode === 'hitbox' }" @click="mode = 'hitbox'">Hitbox 编辑</button>
            </div>
            <div v-if="mode === 'action'" class="preview__row">
              <select v-model="selectedAction">
                <option v-for="action in actionList" :key="action" :value="action">{{ action }}</option>
              </select>
              <button type="button" @click="playAction">执行</button>
            </div>
            <div class="preview__row">
              <button type="button" @click="running = !running">{{ running ? '暂停' : '继续' }}</button>
              <button type="button" @click="stepOnce">单帧</button>
              <button type="button" @click="reset">重置</button>
            </div>
          </div>

          <div v-if="mode === 'hitbox'" class="preview__group">
            <div class="preview__label">交互 Hitbox（点击/双击区域）</div>
            <div class="preview__row">
              <button
                v-for="(hitbox, index) in hitboxes"
                :key="hitbox.id"
                type="button"
                :class="{ active: index === selectedHitbox }"
                @click="selectedHitbox = index"
              >{{ hitbox.name }}</button>
            </div>
            <label>名称
              <input
                :value="hitboxes[selectedHitbox]?.name"
                type="text"
                @change="updateSelectedHitbox({ name: ($event.target as HTMLInputElement).value })"
              >
            </label>
            <label>单击动作
              <select
                :value="hitboxes[selectedHitbox]?.action"
                @change="updateSelectedHitbox({ action: ($event.target as HTMLSelectElement).value })"
              >
                <option v-for="action in actionList" :key="action" :value="action">{{ action }}</option>
              </select>
            </label>
            <label>双击动作
              <select
                :value="hitboxes[selectedHitbox]?.doubleAction || ''"
                @change="updateSelectedHitbox({ doubleAction: ($event.target as HTMLSelectElement).value || undefined })"
              >
                <option value="">（无）</option>
                <option v-for="action in actionList" :key="action" :value="action">{{ action }}</option>
              </select>
            </label>
            <label>
              <input
                :checked="hitboxes[selectedHitbox]?.enabled"
                type="checkbox"
                @change="updateSelectedHitbox({ enabled: ($event.target as HTMLInputElement).checked })"
              > 启用这个区域
            </label>
            <div class="preview__row">
              <button type="button" @click="addHitbox">新增区域</button>
              <button type="button" @click="removeHitbox">删除选中</button>
            </div>
            <div class="preview__hint-line">在画面上拖动区域移动，拖右下角把手缩放；改这里不会改变物理碰撞体。</div>
          </div>

          <div class="preview__group">
            <div class="preview__label">调试叠层</div>
            <label><input v-model="debug.terrain" type="checkbox"> 地形线</label>
            <label><input v-model="debug.colliders" type="checkbox"> 碰撞体 / Hitbox</label>
            <label><input v-model="debug.path" type="checkbox"> 寻路路径</label>
            <label><input v-model="debug.velocity" type="checkbox"> 速度向量</label>
          </div>

          <div class="preview__group">
            <div class="preview__label">尺寸与缩放</div>
            <label>宽 <input v-model.number="runtime.importer.spriteWidth" type="number" min="8" max="2048"></label>
            <label>高 <input v-model.number="runtime.importer.spriteHeight" type="number" min="8" max="2048"></label>
            <label>缩放 <input v-model.number="runtime.importer.scale" type="number" min="0.1" max="4" step="0.1"></label>
          </div>

          <div v-if="analysis" class="preview__group">
            <div class="preview__label">动作映射</div>
            <div v-for="item in runtime.importer.actionMapping" :key="item.actionId" class="preview__mapping">
              <span>{{ item.actionId }}</span>
              <code>{{ item.source }}</code>
            </div>
            <div v-if="analysis.unsupported.length" class="preview__warn">
              <div class="preview__label">不支持的资源</div>
              <div v-for="item in analysis.unsupported" :key="item">{{ item }}</div>
            </div>
            <div v-if="analysis.warnings.length" class="preview__warn">
              <div class="preview__label">提示</div>
              <div v-for="item in analysis.warnings" :key="item">{{ item }}</div>
            </div>
            <div v-if="analysis.errors.length" class="preview__error">
              <div v-for="item in analysis.errors" :key="item">{{ item }}</div>
            </div>
          </div>

          <div v-if="threeInfo || threeError" class="preview__message">
            {{ threeInfo || threeError }}
          </div>
          <div v-if="lastMessage" class="preview__message">{{ lastMessage }}</div>
          <div class="preview__group preview__actions">
            <button type="button" class="preview__primary" :disabled="busy || !analysis?.ok" @click="confirm">
              {{ busy ? '添加中…' : '确认并添加桌面' }}
            </button>
            <button type="button" @click="runtime.cancelImport()">取消</button>
          </div>
          <div v-if="confirmError" class="preview__error">{{ confirmError }}</div>
        </aside>
      </div>
    </div>
  </div>
</template>

<style scoped>
.preview {
  position: absolute;
  inset: 0;
  z-index: 65;
  display: grid;
  place-items: center;
  background: rgba(8, 10, 14, 0.5);
  pointer-events: auto;
}

.preview__panel {
  width: min(1120px, 94vw);
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  border-radius: 18px;
  background: rgba(19, 22, 28, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 26px 60px rgba(0, 0, 0, 0.5);
  color: #e9eff9;
  font-size: 12px;
  overflow: hidden;
}

.preview__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.preview__sub {
  flex: 1;
  color: rgba(196, 210, 232, 0.62);
  font-size: 11px;
}

.preview__close {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.preview__body {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) 300px;
  gap: 12px;
  padding: 12px;
  overflow: hidden;
}

.preview__stage {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.preview__stage-stack {
  position: relative;
  width: 100%;
  border-radius: 12px;
  overflow: hidden;
  background: #11141a;
}

.preview__canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  background: transparent;
  cursor: crosshair;
}

.preview__canvas--gl {
  pointer-events: none;
}

.preview__hint-line {
  color: rgba(196, 210, 232, 0.6);
  font-size: 11px;
}

.preview__side {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  padding-right: 4px;
}

.preview__group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
}

.preview__label {
  color: rgba(196, 210, 232, 0.66);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.preview__row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.preview__row button,
.preview__group button {
  padding: 4px 9px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.06);
  color: inherit;
  font-size: 11px;
  cursor: pointer;
}

.preview__row button.active {
  background: rgba(96, 148, 255, 0.3);
  border-color: rgba(126, 180, 255, 0.6);
}

.preview__group select,
.preview__group input[type='number'] {
  padding: 3px 6px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(0, 0, 0, 0.3);
  color: inherit;
  font-size: 11px;
  width: 76px;
}

.preview__mapping {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: rgba(220, 230, 246, 0.86);
}

.preview__mapping code {
  font-size: 10px;
  color: rgba(160, 200, 255, 0.9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 170px;
}

.preview__warn {
  color: #ffc48a;
  font-size: 10px;
  line-height: 1.5;
}

.preview__error {
  color: #ffb4b4;
  font-size: 10px;
  line-height: 1.5;
}

.preview__message {
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(96, 148, 255, 0.14);
  font-size: 11px;
  line-height: 1.5;
}

.preview__actions {
  flex-direction: row;
  gap: 8px;
}

.preview__primary {
  background: rgba(96, 148, 255, 0.34) !important;
  border-color: rgba(126, 180, 255, 0.6) !important;
}
</style>
