<script setup lang="ts">
/**
 * 瓦片世界实验台：几何判定框 → 体素化瓦片 → 泰拉瑞亚式寻路 → 实验宠执行。
 *
 * user:"比如几何判定框与地图寻路模型，我不要这个透明窗口，你给我单独做一个界面。
 *  最简单的界面，不需要有任何样式，就是把这件事儿给整明白"+
 * "所有的行为完全按照《泰拉瑞亚》去对齐"+
 * (画布直接画出瓦片网格：实心/单向板/绳梯一目了然；宠物的判定框是
 *  泰拉瑞亚式 AABB；寻路结果以瓦片路标展示。)
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { PetWorld } from '../engine/world.ts'
import { TILE_SIZE, type TileCell } from '../engine/tiles.ts'
import type { DesktopWindow } from '../engine/terrain.ts'

const canvasRef = ref<HTMLCanvasElement | null>(null)
const hud = ref('加载中…')
const windowInput = ref('600,260,420,260')
const paused = ref(false)
const showTiles = ref(true)
const showWindows = ref(true)
const showPath = ref(true)
const showBox = ref(true)

const SCREEN = { x: 0, y: 0, width: 1600, height: 900 }

let world: PetWorld
let windows: DesktopWindow[] = []
let windowCounter = 0
let now = 0
let frames = 0
let fpsFrames = 0
let fps = 0
let fpsAt = 0
let mouse: { x: number; y: number } | null = null
let stepOne = false
let raf = 0
let lastPlanText = '—'

function seedWindows(): void {
  // 演示用窗口：下沿都在跳跃射程内（地板 900），宠物能跳上窗口下沿平台，
  // 再沿竖边绳梯爬到窗口顶——不是摆在半空够不着的装饰。
  windows = [
    { id: 'w1', title: '窗口A', className: 'Synthetic', bounds: { x: 220, y: 420, width: 520, height: 260 }, z: 0 },
    { id: 'w2', title: '窗口B', className: 'Synthetic', bounds: { x: 820, y: 360, width: 420, height: 260 }, z: 1 },
  ]
  windowCounter = windows.length
}

function resetWorld(): void {
  world = new PetWorld({ screen: SCREEN, quality: 'balanced', useL3: false, graphRebuildDelayMs: 0 })
  world.applyWindows(windows)
  world.createPet('p1', '实验宠', { x: 800, y: 860 }, {})
}

function addWindow(): void {
  const parts = windowInput.value.split(',').map(v => Number(v.trim()))
  if (parts.length !== 4 || parts.some(v => !Number.isFinite(v))) {
    windowInput.value = '格式：x,y,宽,高'
    return
  }
  windowCounter += 1
  windows.push({
    id: `w${windowCounter}`,
    title: `窗口${windowCounter}`,
    className: 'Synthetic',
    bounds: { x: parts[0]!, y: parts[1]!, width: parts[2]!, height: parts[3]! },
    z: windows.length,
  })
  world.applyWindows(windows)
}

function clearWindows(): void {
  windows = []
  world.applyWindows(windows)
}

function applyWindowsFromInput(): void {
  world.applyWindows(windows)
}

function resetPet(): void {
  world.removePet('p1')
  world.createPet('p1', '实验宠', { x: 800, y: 860 }, {})
}

function onCanvasClick(event: MouseEvent): void {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  const point = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  const pet = world.get('p1')
  if (!pet) return
  const result = pet.setDestination(point, { tiles: world.tileGrid, now })
  lastPlanText = result === 'ok' ? 'ok' : 'unreachable（不可达）'
}

let lastPlan = '—'

function onCanvasMove(event: MouseEvent): void {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  mouse = { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

function onCanvasLeave(): void {
  mouse = null
}

function draw(): void {
  const canvas = canvasRef.value
  if (!canvas) return
  const context = canvas.getContext('2d')
  if (!context) return
  context.setTransform(1, 0, 0, 1, 0, 0)
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)

  const grid = world.tileGrid

  // 1) 原始窗口矩形（几何判定框的输入）：灰色虚线。
  if (showWindows.value) {
    context.setLineDash([4, 4])
    context.strokeStyle = 'rgba(120,120,120,0.8)'
    context.lineWidth = 1
    for (const window of windows) {
      const { x, y, width, height } = window.bounds
      context.strokeRect(x, y, width, height)
      context.fillStyle = 'rgba(120,120,120,0.9)'
      context.fillText(window.title, x + 4, y + 12)
    }
    context.setLineDash([])
  }

  // 2) 瓦片网格（体素化的地图）：实心=灰、单向板=橙、绳梯=蓝。
  if (showTiles.value) {
    for (let row = 0; row < grid.rows; row += 1) {
      for (let col = 0; col < grid.cols; col += 1) {
        const type = grid.typeAt(col, row)
        if (type === 0) continue
        const x = grid.bounds.x + col * TILE_SIZE
        const y = grid.bounds.y + row * TILE_SIZE
        if (type === 1) {
          context.fillStyle = 'rgba(130,140,155,0.85)'
          context.fillRect(x, y, TILE_SIZE, TILE_SIZE)
        } else if (type === 2) {
          context.fillStyle = 'rgba(255,150,20,0.95)'
          context.fillRect(x, y, TILE_SIZE, 6)
          context.fillStyle = 'rgba(255,150,20,0.25)'
          context.fillRect(x, y + 6, TILE_SIZE, TILE_SIZE - 6)
        } else {
          context.strokeStyle = 'rgba(60,110,220,0.9)'
          context.lineWidth = 2
          context.beginPath()
          context.moveTo(x + TILE_SIZE / 2, y)
          context.lineTo(x + TILE_SIZE / 2, y + TILE_SIZE)
          context.stroke()
        }
      }
    }
  }

  const pet = world.get('p1')

  // 3) 瓦片路标路径（绿色方块）。
  if (showPath.value && pet) {
    const path: TileCell[] = pet.plannedTilePath
    context.strokeStyle = 'rgba(30,170,60,0.95)'
    context.lineWidth = 2
    // 16px 瓦片下格很小：内缩按比例算，保证路标一眼能看清。
    const inset = Math.max(1, Math.round(TILE_SIZE * 0.2))
    for (const cell of path) {
      context.strokeRect(
        grid.bounds.x + cell.col * TILE_SIZE + inset,
        grid.bounds.y + cell.row * TILE_SIZE + inset,
        TILE_SIZE - inset * 2,
        TILE_SIZE - inset * 2,
      )
    }
    const goal = pet.currentGoal
    if (goal) {
      context.beginPath()
      context.arc(goal.x, goal.y, 8, 0, Math.PI * 2)
      context.stroke()
    }
  }

  // 4) 实验宠：泰拉瑞亚式判定框（AABB）+ 速度向量。
  if (pet) {
    if (showBox.value) {
      const box = pet.renderRect()
      context.strokeStyle = 'rgba(40,90,220,0.95)'
      context.lineWidth = 2
      context.strokeRect(box.x, box.y, box.width, box.height)
      context.strokeStyle = 'rgba(220,120,20,0.95)'
      context.beginPath()
      context.moveTo(pet.body.x, pet.body.y)
      context.lineTo(pet.body.x + pet.body.vx * 0.06, pet.body.y + pet.body.vy * 0.06)
      context.stroke()
    }
  }
}

function updateHud(): void {
  const pet = world.get('p1')
  const stats = world.stats()
  const d = pet?.diagnostics()
  hud.value = [
    `tick=${now.toFixed(0)}ms fps=${fps.toFixed(0)}`,
    `地形段=${stats.terrainSegments} 瓦片=${stats.tileCols}×${stats.tileRows} 实心=${stats.tileSolid} 单向板=${stats.tilePlatform} 绳梯=${stats.tileLadder} 建图=${stats.lastTileBuildMs.toFixed(1)}ms`,
    `规划=${lastPlan} 路标=${d ? `${d.pathIndex}/${d.pathNodes}` : '—'} 目标=${d?.goal ? `(${d.goal.x.toFixed(0)},${d.goal.y.toFixed(0)})` : '无'} 行为=${d?.behavior ?? '—'}`,
    `宠物=(${d?.position.x.toFixed(0)},${d?.position.y.toFixed(0)}) 速度=(${d?.velocity.x.toFixed(0)},${d?.velocity.y.toFixed(0)}) 动作=${d?.actionId ?? '—'} 接地=${d?.grounded ?? '—'} 挂=${d?.hung ?? '—'} 爬=${d?.climbing ?? '—'}`,
  ].join('\n')
}

function frame(): void {
  raf = requestAnimationFrame(frame)
  if (!paused.value || stepOne) {
    now += 16
    world.tick(now, 16, mouse)
    stepOne = false
  }
  draw()
  frames += 1
  fpsFrames += 1
  if (now - fpsAt >= 1000) {
    fps = fpsFrames / ((now - fpsAt) / 1000)
    fpsFrames = 0
    fpsAt = now
  }
  if (frames % 6 === 0) updateHud()
}

onMounted(() => {
  seedWindows()
  resetWorld()
  frame()
})

onBeforeUnmount(() => cancelAnimationFrame(raf))

function stepOnceFrame(): void {
  stepOne = true
}
</script>

<template>
  <div>
    <div>
      <button type="button" @click="paused = !paused">{{ paused ? '继续' : '暂停' }}</button>
      <button type="button" @click="stepOnceFrame">单步</button>
      <button type="button" @click="resetPet">重置宠物</button>
      <input v-model="windowInput" size="14" />
      <button type="button" @click="addWindow">添加窗口</button>
      <button type="button" @click="applyWindowsFromInput">应用窗口</button>
      <button type="button" @click="clearWindows">清空窗口</button>
      <label><input v-model="showWindows" type="checkbox">窗口框</label>
      <label><input v-model="showTiles" type="checkbox">瓦片</label>
      <label><input v-model="showPath" type="checkbox">路径</label>
      <label><input v-model="showBox" type="checkbox">判定框</label>
    </div>
    <pre>{{ hud }}</pre>
    <canvas
      ref="canvasRef"
      :width="SCREEN.width"
      :height="SCREEN.height"
      @click="onCanvasClick"
      @mousemove="onCanvasMove"
      @mouseleave="onCanvasLeave"
    ></canvas>
    <pre>左键点画布=设目标；灰方块=实心瓦 橙条=单向板瓦（可穿/可落） 蓝竖线=绳梯瓦（可爬）；
绿框=寻路路标；蓝框=宠物判定框（AABB）。点击目标后宠物按泰拉瑞亚 NPC 语义走/跳/落/爬。</pre>
  </div>
</template>
