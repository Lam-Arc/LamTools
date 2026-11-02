<script setup lang="ts">
/**
 * 主界面「桌宠」设置页。
 *
 * user:“桌宠设置：在设置里单独放一份，并持久化。这份的持久化是唯一源。包括右键
 * 出来的那个面板，修改之后也应该是去改这个持久化的文件，ping也是同理”+
 * (本页只通过 configFile.ts 读写 .lam/pet/config.json；桌宠面板、右键菜单、
 *  Ping 面板写的是同一份文件，所有窗口收到 config-changed 后重读。)
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { defaultConfig, DEFAULT_PING_PROMPTS, type PetConfigV1, type PingSectorConfig } from '@/pet/config.ts'
import { hasPetConfigAccess, patchPetConfig, readPetConfig, updatePetConfig } from '@/pet/configFile.ts'

const available = hasPetConfigAccess()
const config = reactive<PetConfigV1>(defaultConfig())
const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const error = ref('')

const qualityOptions = [
  { value: 'low', label: '低（更快，线段更少）' },
  { value: 'balanced', label: '均衡' },
  { value: 'high', label: '高（更贴边缘）' },
] as const

const zModeOptions = [
  { value: 'top', label: '置顶（总在窗口之上）' },
  { value: 'clip', label: '置顶 + 按窗口几何裁剪（推荐）' },
  { value: 'behind', label: '压到窗口之下（整层被挡）' },
] as const

const bubbleOptions = [
  { value: 'popup', label: '主动弹出' },
  { value: 'badge', label: '只显示角标' },
  { value: 'silent', label: '静默' },
] as const

const bubbleRows = [
  { key: 'question', label: 'Agent 提问' },
  { key: 'approval', label: '审批' },
  { key: 'reply', label: '普通回复' },
  { key: 'done', label: '任务完成' },
] as const

const sectors = computed(() => config.ping.sectors)

function report(message: string): void {
  error.value = message
}

async function load(): Promise<void> {
  if (!available) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const next = await readPetConfig()
    Object.assign(config, next || defaultConfig())
  } catch (cause) {
    report(cause instanceof Error ? cause.message : String(cause))
  } finally {
    loading.value = false
  }
}

// 顶层字段：防抖后提交自己拥有的片段；Rust 侧递归合并，不覆盖别的窗口字段。
let pending: Record<string, unknown> = {}
let saveTimer = 0
let revision = 0

function mergePatch(target: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  for (const [key, value] of Object.entries(patch)) {
    const current = target[key]
    if (value && typeof value === 'object' && !Array.isArray(value)
      && current && typeof current === 'object' && !Array.isArray(current)) {
      target[key] = mergePatch({ ...(current as Record<string, unknown>) }, value as Record<string, unknown>)
    } else {
      target[key] = value
    }
  }
  return target
}

function queuePatch(patch: Record<string, unknown>): void {
  revision += 1
  pending = mergePatch(pending, patch)
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => { void flush() }, 300)
}

async function flush(): Promise<void> {
  if (!Object.keys(pending).length) return
  const patch = pending
  const at = revision
  pending = {}
  saving.value = true
  error.value = ''
  try {
    await patchPetConfig(patch)
    if (revision === at) {
      saved.value = true
      window.setTimeout(() => { saved.value = false }, 1600)
    }
  } catch (cause) {
    report(cause instanceof Error ? cause.message : String(cause))
  } finally {
    saving.value = false
  }
}

async function setEnabled(value: boolean): Promise<void> {
  config.enabled = value
  saving.value = true
  error.value = ''
  try {
    // 先落盘再开关窗口：否则新窗口 boot 时读到的还是旧的 enabled=false，
    // 会立刻把自己关掉。
    await patchPetConfig({ enabled: value })
    const { invoke } = await import('@tauri-apps/api/core')
    if (value) await invoke('pet_overlay_open')
    else await invoke('pet_overlay_close')
    saved.value = true
    window.setTimeout(() => { saved.value = false }, 1600)
  } catch (cause) {
    report(cause instanceof Error ? cause.message : String(cause))
  } finally {
    saving.value = false
  }
}

function setL3(value: boolean): void {
  config.useL3 = value
  queuePatch({ useL3: value })
}

function setQuality(value: PetConfigV1['quality']): void {
  config.quality = value
  queuePatch({ quality: value })
}

function setZMode(value: PetConfigV1['zMode']): void {
  config.zMode = value
  queuePatch({ zMode: value })
  void import('@tauri-apps/api/core')
    .then(({ invoke }) => invoke('pet_set_z_mode', { mode: value }))
    .catch(() => undefined)
}

function setBubble(key: string, value: string): void {
  ;(config.bubbles as unknown as Record<string, unknown>)[key] = value
  queuePatch({ bubbles: { [key]: value } })
}

function setBubbleMax(value: number): void {
  config.bubbles.maxExpanded = value
  queuePatch({ bubbles: { maxExpanded: value } })
}

function setPingField(key: string, value: unknown): void {
  ;(config.ping as unknown as Record<string, unknown>)[key] = value
  queuePatch({ ping: { [key]: value } })
  if (key === 'hotkey') {
    void import('@tauri-apps/api/core')
      .then(({ invoke }) => invoke('pet_hotkey_set', { accelerator: value }))
      .catch(() => undefined)
  }
}

function setSector(index: number, key: keyof PingSectorConfig, value: unknown): void {
  const sector = config.ping.sectors[index]
  if (!sector) return
  ;(sector as unknown as Record<string, unknown>)[key] = value
  queuePatch({ ping: { sectors: JSON.parse(JSON.stringify(config.ping.sectors)) } })
}

function addSector(): void {
  config.ping.sectors = [
    ...config.ping.sectors,
    { id: `custom-${Date.now().toString(36)}`, label: '新项', icon: '＋', kind: 'custom', color: '#B9C6DB', enabled: true },
  ]
  queuePatch({ ping: { sectors: JSON.parse(JSON.stringify(config.ping.sectors)) } })
}

function removeSector(index: number): void {
  config.ping.sectors = config.ping.sectors.filter((_, at) => at !== index)
  queuePatch({ ping: { sectors: JSON.parse(JSON.stringify(config.ping.sectors)) } })
}

function resetPrompt(sector: PingSectorConfig): void {
  if (sector.kind === 'question') sector.prompt = DEFAULT_PING_PROMPTS.question
  if (sector.kind === 'exclamation') sector.prompt = DEFAULT_PING_PROMPTS.exclamation
  if (sector.kind === 'note') sector.prompt = DEFAULT_PING_PROMPTS.note
  queuePatch({ ping: { sectors: JSON.parse(JSON.stringify(config.ping.sectors)) } })
}

// 每只桌宠的可见/缩放：先读最新文件再按 id 合并，避免覆盖别人刚导入的角色。
let petPending: Record<string, Record<string, unknown>> = {}
let petTimer = 0
function queuePetField(id: string, field: string, value: unknown): void {
  petPending[id] = { ...(petPending[id] || {}), [field]: value }
  if (petTimer) window.clearTimeout(petTimer)
  petTimer = window.setTimeout(() => { void flushPets() }, 300)
}

async function flushPets(): Promise<void> {
  const pendingPets = petPending
  petPending = {}
  if (!Object.keys(pendingPets).length) return
  saving.value = true
  try {
    const next = await updatePetConfig(latest => ({
      pets: latest.pets.map(record => pendingPets[record.id] ? { ...record, ...pendingPets[record.id] } : record),
    }))
    config.pets = next.pets
    saved.value = true
    window.setTimeout(() => { saved.value = false }, 1600)
  } catch (cause) {
    report(cause instanceof Error ? cause.message : String(cause))
  } finally {
    saving.value = false
  }
}

let unlisten: (() => void) | null = null
onMounted(() => {
  void load()
  if (!available) return
  void import('@tauri-apps/api/event').then(({ listen }) => {
    void listen('pet://config-changed', () => {
      // 自己刚写入的广播不重载，避免覆盖正在编辑的草稿。
      if (loading.value || saving.value || Object.keys(pending).length || Object.keys(petPending).length) return
      void load()
    }).then(off => { unlisten = off })
  }).catch(() => undefined)
})

onBeforeUnmount(() => {
  if (saveTimer) window.clearTimeout(saveTimer)
  if (petTimer) window.clearTimeout(petTimer)
  unlisten?.()
})
</script>

<template>
  <div class="pet-settings-editor">
    <p v-if="!available" class="pet-settings-hint">
      桌宠设置仅在桌面版可用；这里读写的是应用数据目录下的 <code>.lam/pet/config.json</code>。
    </p>
    <template v-else>
      <p class="pet-settings-hint">
        所有桌宠相关窗口共用这一份配置：主界面设置、桌宠右键面板、Ping 面板修改后都会写回
        <code>.lam/pet/config.json</code>。
        <span v-if="saving" class="pet-settings-state">正在保存…</span>
        <span v-else-if="saved" class="pet-settings-state pet-settings-state--ok">已保存</span>
      </p>
      <p v-if="error" class="pet-settings-error" role="alert">{{ error }}</p>

      <article class="setting-card">
        <div class="subhead">
          <span class="muted subhead-title">总开关</span>
        </div>
        <label class="pet-settings-row">
          <span>启用桌宠</span>
          <input type="checkbox" :checked="config.enabled" @change="setEnabled(($event.target as HTMLInputElement).checked)">
        </label>
        <p class="pet-settings-hint">关闭后会收起桌宠覆盖层；Ping 独立窗口不受影响。</p>
      </article>

      <article class="setting-card">
        <div class="subhead">
          <span class="muted subhead-title">桌面与地形</span>
        </div>
        <label class="pet-settings-row">
          <span>真实遮挡模式</span>
          <select :value="config.zMode" @change="setZMode(($event.target as HTMLSelectElement).value as PetConfigV1['zMode'])">
            <option v-for="option in zModeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="pet-settings-row">
          <span>L3 视觉边缘识别</span>
          <input type="checkbox" :checked="config.useL3" @change="setL3(($event.target as HTMLInputElement).checked)">
        </label>
        <p class="pet-settings-hint">默认关闭：不抓屏、不建视觉地形；需要时再打开。</p>
        <label class="pet-settings-row">
          <span>几何精度</span>
          <select :value="config.quality" @change="setQuality(($event.target as HTMLSelectElement).value as PetConfigV1['quality'])">
            <option v-for="option in qualityOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
      </article>

      <article class="setting-card">
        <div class="subhead">
          <span class="muted subhead-title">桌宠</span>
        </div>
        <p v-if="!config.pets.length" class="pet-settings-hint">还没有桌宠；在桌宠覆盖层的设置里导入角色。</p>
        <div v-for="record in config.pets" :key="record.id" class="pet-settings-row pet-settings-row--pet">
          <span class="pet-settings-name">{{ record.name }}</span>
          <label class="pet-settings-inline">
            <input type="checkbox" :checked="record.visible" @change="queuePetField(record.id, 'visible', ($event.target as HTMLInputElement).checked)">
            显示
          </label>
          <label class="pet-settings-inline">
            缩放
            <input
              type="number" min="0.3" max="3" step="0.05"
              :value="record.scale"
              @change="queuePetField(record.id, 'scale', Number(($event.target as HTMLInputElement).value))"
            >
          </label>
        </div>
      </article>

      <article class="setting-card">
        <div class="subhead">
          <span class="muted subhead-title">Ping 环</span>
        </div>
        <label class="pet-settings-row">
          <span>快捷键（按住显示，松开执行）</span>
          <input
            type="text"
            :value="config.ping.hotkey"
            @change="setPingField('hotkey', ($event.target as HTMLInputElement).value)"
          >
        </label>
        <label class="pet-settings-row">
          <span>环半径</span>
          <input type="number" min="60" max="420" :value="config.ping.radius" @change="setPingField('radius', Number(($event.target as HTMLInputElement).value))">
        </label>
        <label class="pet-settings-row">
          <span>环身宽度</span>
          <input type="number" min="4" max="48" :value="config.ping.ringWidth" @change="setPingField('ringWidth', Number(($event.target as HTMLInputElement).value))">
        </label>
        <label class="pet-settings-row">
          <span>「对话」自动附当前截图</span>
          <input type="checkbox" :checked="config.ping.autoAttachScreenshot" @change="setPingField('autoAttachScreenshot', ($event.target as HTMLInputElement).checked)">
        </label>

        <div class="pet-settings-sectors">
          <div v-for="(sector, index) in sectors" :key="sector.id" class="pet-settings-sector">
            <input class="pet-settings-sector-icon" :value="sector.icon" maxlength="2" @change="setSector(index, 'icon', ($event.target as HTMLInputElement).value)">
            <input class="pet-settings-sector-label" :value="sector.label" @change="setSector(index, 'label', ($event.target as HTMLInputElement).value)">
            <input type="color" :value="sector.color" @change="setSector(index, 'color', ($event.target as HTMLInputElement).value)">
            <label class="pet-settings-inline">
              <input type="checkbox" :checked="sector.enabled" @change="setSector(index, 'enabled', ($event.target as HTMLInputElement).checked)">
              启用
            </label>
            <button type="button" class="pet-settings-danger" @click="removeSector(index)">删除</button>
            <textarea
              v-if="sector.kind === 'question' || sector.kind === 'exclamation' || sector.kind === 'note'"
              class="pet-settings-sector-prompt"
              rows="2"
              :value="sector.prompt"
              @change="setSector(index, 'prompt', ($event.target as HTMLTextAreaElement).value)"
            />
            <button
              v-if="sector.kind === 'question' || sector.kind === 'exclamation' || sector.kind === 'note'"
              type="button"
              class="pet-settings-reset"
              @click="resetPrompt(sector)"
            >恢复默认提示词</button>
          </div>
          <button type="button" class="btn btn--ghost" @click="addSector">增加一项</button>
        </div>
      </article>

      <article class="setting-card">
        <div class="subhead">
          <span class="muted subhead-title">气泡与通知</span>
        </div>
        <label v-for="row in bubbleRows" :key="row.key" class="pet-settings-row">
          <span>{{ row.label }}</span>
          <select :value="config.bubbles[row.key]" @change="setBubble(row.key, ($event.target as HTMLSelectElement).value)">
            <option v-for="option in bubbleOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="pet-settings-row">
          <span>最多同时展开</span>
          <input
            type="number" min="1" max="4"
            :value="config.bubbles.maxExpanded"
            @change="setBubbleMax(Number(($event.target as HTMLInputElement).value))"
          >
        </label>
      </article>
    </template>
  </div>
</template>

<style scoped>
.pet-settings-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px 2px 24px;
}
.pet-settings-hint {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.pet-settings-state {
  margin-left: 8px;
  color: var(--muted);
}
.pet-settings-state--ok {
  color: var(--success, #4f9d69);
}
.pet-settings-error {
  margin: 0;
  color: var(--danger, #c0392b);
  font-size: 12px;
}
.pet-settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 30px;
  font-size: 12px;
}
.pet-settings-row--pet {
  justify-content: flex-start;
  gap: 16px;
}
.pet-settings-name {
  min-width: 120px;
  font-weight: 600;
}
.pet-settings-inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.pet-settings-row select,
.pet-settings-row input[type='text'],
.pet-settings-row input[type='number'] {
  min-width: 180px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--control);
  color: var(--control-text);
}
.pet-settings-row--pet input[type='number'] {
  min-width: 72px;
  width: 72px;
}
.pet-settings-sectors {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.pet-settings-sector {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.pet-settings-sector input[type='text'],
.pet-settings-sector input:not([type]) {
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--control);
  color: var(--control-text);
}
.pet-settings-sector-icon {
  width: 36px;
  text-align: center;
}
.pet-settings-sector-label {
  min-width: 90px;
}
.pet-settings-sector-prompt {
  flex: 1 0 100%;
  min-height: 44px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
}
.pet-settings-danger {
  color: var(--danger, #c0392b);
  background: transparent;
  border: none;
  cursor: pointer;
}
.pet-settings-reset {
  background: transparent;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 11px;
}
</style>
