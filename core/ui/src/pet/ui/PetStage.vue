<script setup lang="ts">
/** 画布舞台：只负责把引擎状态画出来，并给出可观测的诊断信息。 */
import { computed, onMounted, ref, type PropType } from 'vue'
import type { PetRuntime } from './usePetRuntime.ts'
import { maskSvgUrl, shouldMaskPets } from '../render/occlusion.ts'

const props = defineProps<{ runtime: PetRuntime }>()
const canvas = ref<HTMLCanvasElement | null>(null)
const glCanvas = ref<HTMLCanvasElement | null>(null)
const debugCanvas = ref<HTMLCanvasElement | null>(null)
// 诊断模式（?diag=1，见 pet::diag_mode）下 HUD 自动展开，截图能直接看到状态。
const showHud = ref(new URLSearchParams(window.location.search).has('diag'))

onMounted(() => {
  props.runtime.attachCanvas(canvas.value)
  // 3D 层：惰性创建，只有角色用到 GLB/glTF 时才付出 WebGL 的代价。
  void props.runtime.attachThreeCanvas(glCanvas.value)
  props.runtime.attachDebugCanvas(debugCanvas.value)
})

function diagnostics() {
  return props.runtime.world.value?.diagnostics() || []
}

/**
 * 局部遮挡：置顶模式下按真实窗口矩形挖掉宠物那一片。
 * 只作用在画布容器上，卡片、气泡、轮盘仍然显示在窗口之上。
 */
const maskStyle = computed<Record<string, string>>(() => {
  const empty: Record<string, string> = {}
  const config = props.runtime.config
  if (config.zMode !== 'clip') return empty
  const overlay = props.runtime.overlay
  const list = props.runtime.windows.value.map(bounds => ({
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
  }))
  if (!shouldMaskPets('clip', list.length)) return empty
  const url = maskSvgUrl(
    { x: overlay.x, y: overlay.y, width: overlay.width, height: overlay.height },
    list,
  )
  if (!url) return empty
  return {
    maskImage: `url("${url}")`,
    webkitMaskImage: `url("${url}")`,
    maskSize: '100% 100%',
    webkitMaskSize: '100% 100%',
    maskRepeat: 'no-repeat',
    webkitMaskRepeat: 'no-repeat',
  }
})
</script>

<template>
  <div class="pet-stage" data-region="pet-stage">
    <div class="pet-stage__pets" :style="maskStyle">
      <canvas ref="canvas" class="pet-stage__canvas" />
      <canvas ref="glCanvas" class="pet-stage__canvas pet-stage__canvas--gl" aria-hidden="true" />
      <canvas ref="debugCanvas" class="pet-stage__canvas pet-stage__canvas--debug" aria-hidden="true" />
    </div>
    <div v-if="showHud" class="pet-stage__hud" data-pet-hit>
      <div class="pet-stage__row">
        FPS {{ runtime.stats.fps }} · tick {{ runtime.stats.tickMs.toFixed(1) }}ms ·
        draw {{ runtime.stats.drawMs.toFixed(1) }}ms
      </div>
      <div class="pet-stage__row">
        地形 {{ runtime.worldStats.value.terrainSegments }} 段 ·
        瓦片 {{ runtime.worldStats.value.tileSolid }}/{{ runtime.worldStats.value.tilePlatform }}/{{ runtime.worldStats.value.tileLadder }} ·
        建图 {{ runtime.worldStats.value.lastTileBuildMs.toFixed(1) }}ms
      </div>
      <div v-for="item in diagnostics()" :key="item.id" class="pet-stage__pet">
        <div>{{ item.id }} · {{ item.actionLabel }}（{{ item.actionId }}）</div>
        <div>物理：{{ item.grounded ? '站立' : item.hung ? '悬挂' : item.climbing ? '攀爬' : '空中' }}
          · v({{ item.velocity.x.toFixed(0) }}, {{ item.velocity.y.toFixed(0) }})</div>
        <div>路径 {{ item.pathIndex }}/{{ item.pathNodes }} · 目标
          {{ item.goal ? `${item.goal.x.toFixed(0)},${item.goal.y.toFixed(0)}` : '无' }}</div>
        <div>行为：{{ item.behavior }}</div>
        <div>切换：{{ item.transition }}</div>
        <div v-if="item.missingAnimation" class="pet-stage__warn">
          动画缺失：{{ item.missingAnimation }}（已回退，物理照常）
        </div>
      </div>
      <div class="pet-stage__row">
        3D：{{ runtime.threeState.enabled ? '已启用' : '未启用' }} · 模型 {{ runtime.threeState.models }} · 实例 {{ runtime.threeState.slots }}
        <span v-if="runtime.threeState.error"> · {{ runtime.threeState.error }}</span>
      </div>
      <div class="pet-stage__row">路由：{{ runtime.agents.value?.lastRoute || '—' }}</div>
      <!-- 截图状态属于 Ping（独立窗口），不再显示在桌宠 HUD 里。 -->
    </div>
  </div>
</template>

<style scoped>
.pet-stage {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.pet-stage__pets {
  position: absolute;
  inset: 0;
  /* 遮挡遮罩只剪这层：其他 UI 不受影响。 */
}

.pet-stage__canvas {
  position: absolute;
  left: 0;
  top: 0;
  display: block;
  /* 画布本身穿透；角色命中由 Rust 侧的矩形决定。 */
  pointer-events: none;
}

/* 3D 画布叠在 2D 之上：2D 角色仍在下面正常绘制，互不干扰。 */
.pet-stage__canvas--gl {
  background: transparent;
}

.pet-stage__hud {
  position: absolute;
  left: 12px;
  bottom: 12px;
  min-width: 320px;
  max-width: 520px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(16, 18, 23, 0.86);
  border: 1px solid rgba(255, 255, 255, 0.12);
  font-family: ui-monospace, monospace;
  font-size: 11px;
  line-height: 1.55;
  color: #cfd8e6;
  pointer-events: auto;
}

.pet-stage__row {
  color: #93a2b8;
}

.pet-stage__pet {
  margin: 6px 0;
  padding-top: 6px;
  border-top: 1px dashed rgba(255, 255, 255, 0.12);
}

.pet-stage__warn {
  color: #ffc48a;
}
</style>
