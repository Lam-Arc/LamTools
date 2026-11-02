<script setup lang="ts">
/**
 * 桌宠设置：外观、Ping 环与提示词、气泡策略、性能、角色与绑定。
 *
 * 所有默认值都来自 config.ts，改完即时生效并落盘（带版本号）。
 */
import { computed, ref, type PropType } from 'vue'
import { DEFAULT_PING_PROMPTS, type PingSectorConfig } from '../config.ts'
import type { PetRuntime } from './usePetRuntime.ts'

const props = defineProps<{ runtime: PetRuntime }>()
const emit = defineEmits<{ close: [] }>()

const sectors = computed(() => props.runtime.config.ping.sectors)

// user:“这个内外环半径可调节吗”+(内环=中心盘独立可调；未设置时按外径 42% 自动算，
// 外环继续由「环半径 + 环身宽度」决定。)
const hubRadius = computed({
  get: () => props.runtime.config.ping.hubRadius
    ?? Math.round((props.runtime.config.ping.radius + props.runtime.config.ping.ringWidth / 2) * 0.42),
  set: (value: number) => {
    props.runtime.config.ping.hubRadius = Math.max(10, Math.round(value))
    props.runtime.scheduleSave()
  },
})

// user:“支持图片或动图背景”+(Ping 环背景支持 PNG/JPEG/WebP/GIF：读成 data URL
// 存进配置，图片和动图都由页面直接渲染，不需要额外路径权限。)
const BACKGROUND_MAX_BYTES = 4 * 1024 * 1024
const backgroundError = ref('')

async function pickRingBackground(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  backgroundError.value = ''
  if (!file.type.startsWith('image/')) {
    backgroundError.value = '请选择图片或动图文件'
    return
  }
  if (file.size > BACKGROUND_MAX_BYTES) {
    backgroundError.value = '背景文件不能超过 4MB'
    return
  }
  try {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result || ''))
      reader.onerror = () => reject(reader.error || new Error('读取图片失败'))
      reader.readAsDataURL(file)
    })
    if (!dataUrl.startsWith('data:image/')) {
      backgroundError.value = '请选择图片或动图文件'
      return
    }
    props.runtime.config.ping.background = dataUrl
    props.runtime.scheduleSave()
  } catch (error) {
    backgroundError.value = error instanceof Error ? error.message : String(error)
  }
}

function clearRingBackground(): void {
  props.runtime.config.ping.background = undefined
  backgroundError.value = ''
  props.runtime.scheduleSave()
}

function addSector(): void {
  const id = `custom-${Date.now().toString(36)}`
  props.runtime.config.ping.sectors = [
    ...props.runtime.config.ping.sectors,
    {
      id,
      label: '新项',
      icon: '＋',
      kind: 'custom',
      color: '#B9C6DB',
      enabled: true,
    },
  ]
  props.runtime.scheduleSave()
}

function removeSector(id: string): void {
  props.runtime.config.ping.sectors = props.runtime.config.ping.sectors.filter(sector => sector.id !== id)
  props.runtime.scheduleSave()
}

function resetPrompt(sector: PingSectorConfig): void {
  if (sector.kind === 'question') sector.prompt = DEFAULT_PING_PROMPTS.question
  if (sector.kind === 'exclamation') sector.prompt = DEFAULT_PING_PROMPTS.exclamation
  if (sector.kind === 'note') sector.prompt = DEFAULT_PING_PROMPTS.note
  props.runtime.scheduleSave()
}

async function applyHotkey(value: string): Promise<void> {
  props.runtime.config.ping.hotkey = value
  props.runtime.scheduleSave()
  const bridge = await import('../bridge.ts')
  await bridge.setPingHotkey(value).catch(() => {})
}

async function applyZMode(value: 'top' | 'behind' | 'clip'): Promise<void> {
  props.runtime.config.zMode = value
  props.runtime.scheduleSave()
  const bridge = await import('../bridge.ts')
  await bridge.setZMode(value).catch(() => {})
}

function startImport(): void {
  void props.runtime.startImportFromFolder()
}

/** 方块人（或任何带皮肤的动作）才显示换肤入口。 */
function hasBlocky(record: { actions: Record<string, unknown> }): boolean {
  return Object.values(record.actions || {}).some(clip => (clip as { type?: string } | null)?.type === 'blocky')
}
</script>

<template>
  <div class="settings" role="dialog" aria-label="桌宠设置">
    <div class="settings__panel" data-pet-hit>
      <header class="settings__head">
        <strong>桌宠设置</strong>
        <span class="settings__version">配置 v{{ runtime.config.version }}</span>
        <button type="button" class="settings__close" @click="emit('close')">✕</button>
      </header>

      <div class="settings__body">
        <section class="settings__group">
          <h4>角色</h4>
          <div class="settings__row">
            <button type="button" @click="startImport">导入角色文件夹…</button>
            <button type="button" @click="runtime.startImportFromFile()">导入单文件…</button>
          </div>
          <div v-if="runtime.petRecords.value.length === 0" class="settings__hint">
            还没有桌宠。导入一张 PNG 就能有一个可跑动、会碰撞的角色，或点下面重建内置方块人。
          </div>
          <div class="settings__row">
            <button type="button" @click="runtime.ensureBlockyPreset()">重建内置方块人预设</button>
          </div>
          <div v-for="record in runtime.petRecords.value" :key="record.id" class="settings__pet">
            <span class="settings__pet-name">{{ record.name }}</span>
            <span class="settings__hint">
              {{ record.spriteWidth }}×{{ record.spriteHeight }} · 碰撞半径 {{ record.radius }}
            </span>
            <button type="button" @click="runtime.togglePetVisible(record.id)">
              {{ record.visible ? '隐藏' : '显示' }}
            </button>
            <template v-if="hasBlocky(record)">
              <button type="button" @click="runtime.importSkinFor(record.id)">导入皮肤…</button>
              <button type="button" @click="runtime.resetSkinFor(record.id)">恢复默认皮肤</button>
            </template>
            <button type="button" @click="runtime.openSessionPicker('pet', record.id)">绑定会话…</button>
            <button type="button" class="settings__danger" @click="runtime.removePet(record.id)">移除</button>
          </div>
        </section>

        <section class="settings__group">
          <h4>桌面与地形</h4>
          <label class="settings__row">
            <span>真实遮挡模式</span>
            <select :value="runtime.config.zMode" @change="applyZMode(($event.target as HTMLSelectElement).value as 'top' | 'behind' | 'clip')">
              <option value="top">置顶（总在窗口之上）</option>
              <option value="clip">置顶 + 按窗口几何裁剪（推荐）</option>
              <option value="behind">压到窗口之下（整层被挡）</option>
            </select>
          </label>
          <label class="settings__row">
            <span>L3 视觉边缘识别</span>
            <input v-model="runtime.config.useL3" type="checkbox" @change="runtime.refreshL3()">
          </label>
          <label class="settings__row">
            <span>几何精度</span>
            <select :value="runtime.config.quality" @change="runtime.setQuality(($event.target as HTMLSelectElement).value as never)">
              <option value="low">低（更快，线段更少）</option>
              <option value="balanced">均衡</option>
              <option value="high">高（更贴边缘）</option>
            </select>
          </label>
          <div class="settings__row">
            <button type="button" @click="runtime.debug.terrain = !runtime.debug.terrain">地形线</button>
            <button type="button" @click="runtime.debug.colliders = !runtime.debug.colliders">碰撞体</button>
            <button type="button" @click="runtime.debug.path = !runtime.debug.path">路径</button>
            <button type="button" @click="runtime.debug.velocity = !runtime.debug.velocity">速度</button>
          </div>
        </section>

        <section class="settings__group">
          <h4>Ping 环</h4>
          <label class="settings__row">
            <span>快捷键（按住显示，松开执行）</span>
            <input
              :value="runtime.config.ping.hotkey"
              type="text"
              @change="applyHotkey(($event.target as HTMLInputElement).value)"
            >
          </label>
          <label class="settings__row">
            <span>环半径（环带中心）</span>
            <input v-model.number="runtime.config.ping.radius" type="number" min="60" max="420" @change="runtime.scheduleSave()">
          </label>
          <label class="settings__row">
            <span>环身宽度（决定外环半径）</span>
            <input v-model.number="runtime.config.ping.ringWidth" type="number" min="4" max="48" @change="runtime.scheduleSave()">
          </label>
          <label class="settings__row">
            <span>内环半径（中心盘）</span>
            <input v-model.number="hubRadius" type="number" min="20" max="360">
          </label>
          <div class="settings__row">
            <span>环背景（图片 / 动图）</span>
            <label class="settings__file">
              选择文件
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif,image/avif"
                @change="pickRingBackground"
              >
            </label>
            <button v-if="runtime.config.ping.background" type="button" @click="clearRingBackground">清除</button>
          </div>
          <div v-if="runtime.config.ping.background" class="settings__ring-bg">
            <img :src="runtime.config.ping.background" alt="Ping 环背景预览">
          </div>
          <div v-if="backgroundError" class="settings__error">{{ backgroundError }}</div>
          <label class="settings__row">
            <span>「对话」自动附当前截图</span>
            <input v-model="runtime.config.ping.autoAttachScreenshot" type="checkbox" @change="runtime.scheduleSave()">
          </label>
          <div class="settings__row">
            <button type="button" @click="runtime.openSessionPicker('ping')">
              切换 Ping 目标会话（当前：{{ runtime.agents.value?.bindings.ping.sessionId?.slice(0, 8) || '未设置' }}）
            </button>
          </div>

          <div class="settings__sectors">
            <div v-for="sector in sectors" :key="sector.id" class="settings__sector">
              <input v-model="sector.icon" class="settings__icon" maxlength="2" @change="runtime.scheduleSave()">
              <input v-model="sector.label" class="settings__label" @change="runtime.scheduleSave()">
              <input v-model="sector.color" type="color" @change="runtime.scheduleSave()">
              <input v-model="sector.enabled" type="checkbox" @change="runtime.scheduleSave()">
              <button type="button" class="settings__danger" @click="removeSector(sector.id)">删除</button>
              <textarea
                v-if="sector.kind === 'question' || sector.kind === 'exclamation' || sector.kind === 'note'"
                v-model="sector.prompt"
                class="settings__prompt"
                rows="2"
                @change="runtime.scheduleSave()"
              />
              <button
                v-if="sector.kind === 'question' || sector.kind === 'exclamation' || sector.kind === 'note'"
                type="button"
                class="settings__reset"
                @click="resetPrompt(sector)"
              >恢复默认提示词</button>
            </div>
            <button type="button" @click="addSector">增加一项</button>
          </div>
        </section>

        <section class="settings__group">
          <h4>气泡与通知</h4>
          <label v-for="key in (['question', 'approval', 'reply', 'done'] as const)" :key="key" class="settings__row">
            <span>{{ key === 'question' ? 'Agent 提问' : key === 'approval' ? '审批' : key === 'reply' ? '普通回复' : '任务完成' }}</span>
            <select v-model="runtime.config.bubbles[key]" @change="runtime.scheduleSave()">
              <option value="popup">主动弹出</option>
              <option value="badge">标记数量</option>
              <option value="silent">静默</option>
            </select>
          </label>
          <label class="settings__row">
            <span>同时展开气泡上限</span>
            <input v-model.number="runtime.config.bubbles.maxExpanded" type="number" min="1" max="4" @change="runtime.scheduleSave()">
          </label>
        </section>

        <section class="settings__group">
          <h4>性能</h4>
          <label class="settings__row">
            <span>渲染上限 FPS</span>
            <input v-model.number="runtime.config.perf.maxFps" type="number" min="15" max="144" @change="runtime.scheduleSave()">
          </label>
          <label class="settings__row">
            <span>L3 刷新周期（秒）</span>
            <input
              :value="Math.round(runtime.config.perf.l3RefreshMs / 1000)"
              type="number" min="5" max="600"
              @change="runtime.config.perf.l3RefreshMs = Number(($event.target as HTMLInputElement).value) * 1000; runtime.scheduleSave()"
            >
          </label>
          <div class="settings__hint">
            FPS {{ runtime.stats.fps }} · 物理 {{ runtime.stats.tickMs.toFixed(1) }}ms ·
            绘制 {{ runtime.stats.drawMs.toFixed(1) }}ms ·
            地形 {{ runtime.worldStats.value.terrainSegments }} 段 ·
            瓦片 {{ runtime.worldStats.value.tileSolid + runtime.worldStats.value.tilePlatform + runtime.worldStats.value.tileLadder }}
          </div>
        </section>

        <section class="settings__group">
          <h4>诊断</h4>
          <div v-if="runtime.configWarnings.value.length" class="settings__hint">
            {{ runtime.configWarnings.value.join('；') }}
          </div>
          <div v-for="error in runtime.errors.value.slice(-6)" :key="error.at" class="settings__error">
            [{{ error.scope }}] {{ error.message }}
          </div>
          <div class="settings__hint">Ping 路由：{{ runtime.agents.value?.lastRoute || '—' }}</div>
          <!-- 截图状态属于 Ping 的独立窗口，不在桌宠设置里显示。 -->
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings {
  position: absolute;
  inset: 0;
  z-index: 68;
  display: grid;
  place-items: center;
  background: rgba(8, 10, 14, 0.5);
  pointer-events: auto;
}

.settings__panel {
  width: min(680px, 92vw);
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  background: rgba(19, 22, 28, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 24px 56px rgba(0, 0, 0, 0.48);
  color: #e9eff9;
  font-size: 12px;
  overflow: hidden;
}

.settings__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.settings__version {
  flex: 1;
  font-size: 10px;
  color: rgba(196, 210, 232, 0.6);
}

.settings__close {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.settings__body {
  padding: 12px 16px 18px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.settings__group h4 {
  margin: 0 0 8px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: rgba(160, 200, 255, 0.85);
}

.settings__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  justify-content: space-between;
}

.settings__row button,
.settings__group button {
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.06);
  color: inherit;
  font-size: 11px;
  cursor: pointer;
}

.settings__row input[type='text'],
.settings__row input[type='number'],
.settings__row select {
  padding: 3px 8px;
  border-radius: 7px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(0, 0, 0, 0.3);
  color: inherit;
  font-size: 11px;
  min-width: 120px;
}

.settings__pet {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border-top: 1px dashed rgba(255, 255, 255, 0.1);
}

.settings__pet-name {
  min-width: 90px;
}

.settings__hint {
  margin-top: 6px;
  font-size: 10px;
  color: rgba(196, 210, 232, 0.62);
  line-height: 1.5;
}

.settings__error {
  font-size: 10px;
  color: #ffb4b4;
  line-height: 1.5;
}

.settings__danger {
  color: #ff9d9d;
}

.settings__sectors {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.settings__sector {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 6px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
}

.settings__icon {
  width: 34px;
  text-align: center;
  padding: 2px 4px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(0, 0, 0, 0.28);
  color: inherit;
}

.settings__label {
  flex: 1;
  min-width: 90px;
  padding: 2px 6px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(0, 0, 0, 0.28);
  color: inherit;
}

.settings__prompt {
  width: 100%;
  resize: vertical;
  padding: 5px 7px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(0, 0, 0, 0.28);
  color: inherit;
  font-size: 11px;
  font-family: inherit;
}

.settings__reset {
  font-size: 10px !important;
}

.settings__file {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(0, 0, 0, 0.28);
  font-size: 11px;
  cursor: pointer;
}

.settings__file input {
  display: none;
}

.settings__ring-bg img {
  display: block;
  max-width: 180px;
  max-height: 120px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  object-fit: cover;
}
</style>
