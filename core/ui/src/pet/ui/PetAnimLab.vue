<script setup lang="ts">
/**
 * 方块人动画实验台：独立页面，只装"方块人姿态"这一块。
 *
 * user:"现在做方块人的动画，用独立的 HTML 给我展示出来，然后底下要可以控制动作组"+
 * (Three.js 直接搭方块人骨架，按 blockyPose 播放；底部按动作组分栏控制，
 *  不依赖透明覆盖层、引擎物理、Ping 与穿透链路。)
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as THREE from 'three'
import { blockyPose, type BlockyModel } from '../render/blocky.ts'
import { createBlockyRig, type BlockyRig } from '../render/blockyRig.ts'
import { createDefaultSkinCanvas, skinCanvasFromBytes } from '../render/blockySkin.ts'

interface ActionEntry {
  id: string
  label: string
}

const ACTION_GROUPS: Array<{ name: string; actions: ActionEntry[] }> = [
  {
    name: '移动',
    actions: [
      { id: 'idle', label: '待机' },
      { id: 'walk', label: '行走' },
      { id: 'jump', label: '跳跃' },
      { id: 'fall', label: '下落' },
      { id: 'land', label: '落地' },
      { id: 'climb', label: '攀爬' },
      { id: 'hang', label: '悬挂' },
    ],
  },
  {
    name: '表演',
    actions: [
      { id: 'jump_happy', label: '开心跳' },
      { id: 'dance', label: '跳舞' },
      { id: 'rest', label: '休息' },
      { id: 'question', label: '疑问' },
    ],
  },
  {
    name: '互动',
    actions: [
      { id: 'interact', label: '互动' },
      { id: 'interact_head', label: '摸头' },
    ],
  },
]

type FacingMode = 'auto' | 'front' | 'back' | 'left' | 'right'

const canvasRef = ref<HTMLCanvasElement | null>(null)
const actionId = ref('idle')
const actionLabel = ref('待机')
const playing = ref(true)
const elapsedMs = ref(0)
const model = ref<BlockyModel>('steve')
const facingMode = ref<FacingMode>('front')
const poseText = ref('')
const skinLabel = ref('默认皮肤')
const fileInputRef = ref<HTMLInputElement | null>(null)
/** 自定义 64×64 皮肤画布；为空时用内置皮肤。 */
let customSkin: HTMLCanvasElement | null = null

let renderer: THREE.WebGLRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let rig: BlockyRig | null = null
let texture: THREE.CanvasTexture | null = null
let raf = 0
let lastFrame = 0

const FACING_MODES: Array<{ id: FacingMode; label: string }> = [
  { id: 'auto', label: '自动（走/爬侧身）' },
  { id: 'front', label: '正面' },
  { id: 'back', label: '背面' },
  { id: 'left', label: '左侧' },
  { id: 'right', label: '右侧' },
]

function facingAngle(): number {
  if (facingMode.value === 'front') return 0
  if (facingMode.value === 'back') return Math.PI
  if (facingMode.value === 'left') return -Math.PI / 2
  if (facingMode.value === 'right') return Math.PI / 2
  return actionId.value === 'walk' || actionId.value === 'climb' ? Math.PI / 2 : 0
}

function buildScene(): void {
  const canvas = canvasRef.value
  if (!canvas) return
  scene = new THREE.Scene()
  scene.background = new THREE.Color('#eef1f4')

  camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100)
  // 留出头顶与脚下的余量，别把方块人裁在画面边缘。
  camera.position.set(0, 0.62, 2.9)
  camera.lookAt(0, 0.52, 0)

  renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1))
  renderer.setClearColor(0xeef1f4, 1)

  scene.add(new THREE.AmbientLight(0xffffff, 1.15))
  const key = new THREE.DirectionalLight(0xffffff, 1.7)
  key.position.set(1.6, 2.2, 2)
  scene.add(key)
  const fill = new THREE.DirectionalLight(0x9db4ff, 0.55)
  fill.position.set(-1.6, 1, -1.2)
  scene.add(fill)

  const grid = new THREE.GridHelper(4, 16, 0xc4ccd6, 0xe1e6eb)
  ;(grid.material as THREE.Material).transparent = true
  ;(grid.material as THREE.Material).opacity = 0.9
  scene.add(grid)

  rebuildRig()
}

function rebuildRig(): void {
  if (!scene) return
  if (rig) {
    scene.remove(rig.root)
    rig.dispose()
    rig = null
  }
  const skin = customSkin ?? createDefaultSkinCanvas(model.value)
  texture?.dispose()
  texture = new THREE.CanvasTexture(skin)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.magFilter = THREE.NearestFilter
  texture.minFilter = THREE.NearestFilter
  texture.generateMipmaps = false
  rig = createBlockyRig(THREE, { model: model.value, texture, textureWidth: 64, textureHeight: 64 })
  // 骨架按 32 个模型单位搭：缩到 1 个单位高，与覆盖层里的方块人同比例。
  rig.root.scale.setScalar(1 / 32)
  scene.add(rig.root)
}

function resize(): void {
  const canvas = canvasRef.value
  if (!canvas || !renderer || !camera) return
  const width = Math.max(1, Math.floor(canvas.clientWidth))
  const height = Math.max(1, Math.floor(canvas.clientHeight))
  const ratio = Math.min(2, window.devicePixelRatio || 1)
  if (canvas.width !== Math.floor(width * ratio) || canvas.height !== Math.floor(height * ratio)) {
    renderer.setPixelRatio(ratio)
    renderer.setSize(width, height, false)
  }
  camera.aspect = width / height
  camera.updateProjectionMatrix()
}

function frame(now: number): void {
  raf = requestAnimationFrame(frame)
  if (!renderer || !scene || !camera) return
  const delta = lastFrame ? Math.min(50, now - lastFrame) : 0
  lastFrame = now
  if (playing.value) elapsedMs.value += delta
  const pose = blockyPose(actionId.value, elapsedMs.value)
  rig?.applyPose(pose)
  if (rig) rig.root.rotation.y = facingAngle()
  poseText.value = `摆臂=${pose.armLeft.x.toFixed(2)} 摆腿=${pose.legLeft.x.toFixed(2)} 起伏=${pose.bob.toFixed(2)}`
  resize()
  renderer.render(scene, camera)
}

function playAction(id: string, label: string): void {
  actionId.value = id
  actionLabel.value = label
  elapsedMs.value = 0
  playing.value = true
}

function togglePlay(): void {
  playing.value = !playing.value
}

function stepOnce(): void {
  playing.value = false
  elapsedMs.value += 16
}

function resetElapsed(): void {
  elapsedMs.value = 0
}

function setModel(next: BlockyModel): void {
  model.value = next
  rebuildRig()
}

function setFacing(mode: FacingMode): void {
  facingMode.value = mode
}

async function applySkinBytes(bytes: Uint8Array, label: string): Promise<void> {
  try {
    customSkin = await skinCanvasFromBytes(bytes)
    skinLabel.value = label
    rebuildRig()
  } catch (error) {
    skinLabel.value = `加载失败：${error instanceof Error ? error.message : String(error)}`
  }
}

function pickSkin(): void {
  fileInputRef.value?.click()
}

async function onSkinFile(file: File | undefined): Promise<void> {
  if (!file) return
  await applySkinBytes(new Uint8Array(await file.arrayBuffer()), file.name)
}

function onDrop(event: DragEvent): void {
  void onSkinFile(event.dataTransfer?.files?.[0])
}

function useDefaultSkin(): void {
  customSkin = null
  skinLabel.value = '默认皮肤'
  rebuildRig()
}

/** 优先加载实验台示例皮肤（public/pet-animlab/user-skin.png）；没有就用内置。 */
async function loadSampleSkin(): Promise<void> {
  try {
    const response = await fetch('/pet-animlab/user-skin.png', { cache: 'no-store' })
    if (!response.ok) throw new Error(String(response.status))
    await applySkinBytes(new Uint8Array(await response.arrayBuffer()), '用户皮肤（示例）')
  } catch {
    customSkin = null
    skinLabel.value = '默认皮肤'
  }
}

onMounted(() => {
  buildScene()
  void loadSampleSkin()
  raf = requestAnimationFrame(frame)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  if (rig) rig.dispose()
  texture?.dispose()
  renderer?.dispose()
  renderer = null
})
</script>

<template>
  <div class="animlab">
    <canvas
      ref="canvasRef"
      class="animlab__canvas"
      @dragover.prevent
      @drop.prevent="onDrop"
    ></canvas>
    <div class="animlab__hud">
      动作={{ actionLabel }}（{{ actionId }}） 时长={{ (elapsedMs / 1000).toFixed(2) }}s {{ poseText }} 皮肤={{ skinLabel }}
    </div>
    <footer class="animlab__controls">
      <div class="animlab__row animlab__row--groups">
        <section v-for="group in ACTION_GROUPS" :key="group.name" class="animlab__group">
          <span class="animlab__group-name">{{ group.name }}</span>
          <button
            v-for="action in group.actions"
            :key="action.id"
            type="button"
            :class="{ active: actionId === action.id }"
            @click="playAction(action.id, action.label)"
          >
            {{ action.label }}
          </button>
        </section>
      </div>
      <div class="animlab__row">
        <button type="button" @click="togglePlay">{{ playing ? '暂停' : '播放' }}</button>
        <button type="button" @click="stepOnce">单步 +16ms</button>
        <button type="button" @click="resetElapsed">回到起点</button>
        <span class="animlab__divider"></span>
        <input ref="fileInputRef" type="file" accept="image/png,image/jpeg" class="animlab__file" @change="onSkinFile(($event.target as HTMLInputElement).files?.[0])" />
        <button type="button" @click="pickSkin">加载皮肤…</button>
        <button type="button" @click="useDefaultSkin">默认皮肤</button>
        <span class="animlab__divider"></span>
        <span class="animlab__label">模型</span>
        <button type="button" :class="{ active: model === 'steve' }" @click="setModel('steve')">Steve</button>
        <button type="button" :class="{ active: model === 'alex' }" @click="setModel('alex')">Alex</button>
        <span class="animlab__divider"></span>
        <span class="animlab__label">朝向</span>
        <button
          v-for="mode in FACING_MODES"
          :key="mode.id"
          type="button"
          :class="{ active: facingMode === mode.id }"
          @click="setFacing(mode.id)"
        >
          {{ mode.label }}
        </button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.animlab {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  margin: 0;
  background: #eef1f4;
  color: #24303c;
  font: 12px/1.5 "Microsoft YaHei", system-ui, sans-serif;
}
.animlab__canvas {
  flex: 1;
  width: 100%;
  min-height: 0;
  display: block;
}
.animlab__hud {
  padding: 4px 10px;
  border-top: 1px solid #d7dde4;
  background: #f8fafc;
  font-family: ui-monospace, Consolas, monospace;
  white-space: pre-wrap;
}
.animlab__controls {
  padding: 6px 10px 10px;
  border-top: 1px solid #d7dde4;
  background: #f4f6f8;
}
.animlab__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding: 3px 0;
}
.animlab__group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-right: 14px;
}
.animlab__group-name {
  color: #66727f;
  margin-right: 2px;
}
.animlab__label {
  color: #66727f;
}
.animlab__divider {
  width: 1px;
  height: 18px;
  margin: 0 8px;
  background: #d7dde4;
}
.animlab button {
  border: 1px solid #c8d0d9;
  border-radius: 4px;
  padding: 3px 8px;
  background: #ffffff;
  color: #24303c;
  font: inherit;
  cursor: pointer;
}
.animlab button:hover {
  background: #eaf0f6;
}
.animlab__file {
  display: none;
}
.animlab button.active {
  border-color: #3b7ddd;
  background: #dbe8fb;
  color: #1c4f9c;
}
</style>
