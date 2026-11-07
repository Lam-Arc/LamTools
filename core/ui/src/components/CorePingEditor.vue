<script setup lang="ts">
/**
 * 主界面「Ping」设置页 / 工作台。
 *
 * user:“Sunday 设置菜单中两个同级独立项：‘桌宠’‘Ping’”+
 * “Ping 是三级同心扇环可视化编辑器，可安全预览/模拟截图标注”+
 * (本页只读写 Ping 领域；预览和选择都在页面内沙盒完成，不注册全局热键、
 *  不发送真实 Agent 消息、不创建整屏覆盖窗口。真正发送仍由生产 Ping 环 +
 *  Sunday 主窗口完成。)
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  defaultPingConfig,
  patchPingConfig,
  patchPingTarget,
  readPingConfig,
  type PingPatch,
} from '@/pet/pingConfigRepository.ts'
import {
  PING_MAX_DEPTH,
  buildPingTree,
  collectSubtreeIds,
  flattenTree,
  movePingSector,
  movePingSectorBeside,
  pingActionLabel,
  reparentPingSector,
} from '@/pet/ping/editorTree.ts'
import { buildRingEditorGeometry } from '@/pet/ping/editorGeometry.ts'
import type { PingConfig, PingSectorConfig, PingSectorKind } from '@/pet/config.ts'
import { DEFAULT_PING_PROMPTS } from '@/pet/config.ts'
import { hasPetConfigAccess } from '@/pet/configFile.ts'
import PingCaptureSandbox from '@/components/PingCaptureSandbox.vue'
import { consumeSettingsDeepLink, onSettingsDeepLink } from '@/helpers/settingsDeepLink.ts'
import { createPetAgentClient, type PetAgentClient } from '@/pet/agent/client.ts'
import * as bridge from '@/pet/bridge.ts'

const available = hasPetConfigAccess()
const config = reactive<PingConfig>(defaultPingConfig())
const selectedId = ref('')
const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const error = ref('')
const sandboxResult = ref('')
const sandboxRingOpen = ref(false)
const sandboxHoverId = ref('')
const PREVIEW_PRESETS = [
  { id: '16-9', label: '16:9 · 1920×1080', width: 1920, height: 1080 },
  { id: 'portrait', label: '竖屏 · 1080×1920', width: 1080, height: 1920 },
  { id: 'square', label: '方形 · 1200×1200', width: 1200, height: 1200 },
  { id: '4-3', label: '4:3 · 1440×1080', width: 1440, height: 1080 },
]
const previewPresetId = ref('16-9')
const previewDpi = ref(100)
const previewPreset = computed(() => PREVIEW_PRESETS.find(item => item.id === previewPresetId.value) || PREVIEW_PRESETS[0])
const previewScale = computed(() => Math.max(1, previewDpi.value) / 100)
const previewLimit = computed(() => Math.max(60, Math.min(
  previewPreset.value.width / previewScale.value,
  previewPreset.value.height / previewScale.value,
) / 2 - 28))
const previewClamped = computed(() => Number(config.radius) > previewLimit.value)
const dragId = ref('')
const dropTargetId = ref('')
const dropPosition = ref<'before' | 'after'>('before')
const projects = ref<{ id: string; name: string }[]>([])
const sessions = ref<{ id: string; title: string }[]>([])
const targetProjectId = ref('')
const targetSessionId = ref('')
const loadingTargets = ref(false)
const targetNotice = ref('')
let targetClient: PetAgentClient | null = null

const KINDS: { value: PingSectorKind; label: string }[] = [
  { value: 'question', label: '提问（截图 + ?）' },
  { value: 'exclamation', label: '注意（截图 + !）' },
  { value: 'note', label: '记录（截图 + 记录）' },
  { value: 'select', label: '框选截图' },
  { value: 'chat', label: '打开会话' },
  { value: 'switch', label: '切换会话' },
  { value: 'subring', label: '子菜单' },
  { value: 'custom', label: '自定义 / 本地动作' },
]

const LOCAL_ACTIONS = [
  { id: 'settings', label: '打开桌宠设置' },
  { id: 'import', label: '导入角色' },
  { id: 'toggle-pets', label: '显示/隐藏桌宠' },
  { id: 'refresh-l3', label: '刷新地形' },
  { id: 'debug-terrain', label: '开关地形线' },
  { id: 'hide-overlay', label: '收起桌宠覆盖层' },
]

const tree = computed(() => buildPingTree(config.sectors))
const nodes = computed(() => flattenTree(tree.value))
const selectedNode = computed(() => nodes.value.find(node => node.sector.id === selectedId.value) || nodes.value[0])
const selected = computed<PingSectorConfig | null>(() => selectedNode.value?.sector || null)
const childCount = computed(() => {
  const node = selectedNode.value
  return node ? node.children.length : 0
})
const geometry = computed(() => buildRingEditorGeometry(config.sectors, {
  radius: Math.min(Number(config.radius) || 132, previewLimit.value),
  ringWidth: Number(config.ringWidth) || 14,
  selectedId: selected.value?.id,
  maxLabelChars: 8,
}))
const selectedArcs = computed(() => geometry.value.bands.flatMap(band => band.arcs))
const enabledRootCount = computed(() => config.sectors.filter(sector => !sector.group && sector.enabled).length)
const enabledTotal = computed(() => config.sectors.filter(sector => sector.enabled).length)

if (!selectedId.value && nodes.value.length > 0) selectedId.value = nodes.value[0].sector.id

async function load(): Promise<void> {
  if (!available) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const next = await readPingConfig()
    Object.assign(config, next)
    targetProjectId.value = next.target?.projectId || ''
    targetSessionId.value = next.target?.sessionId || ''
    if (!nodes.value.some(node => node.sector.id === selectedId.value)) {
      selectedId.value = nodes.value[0]?.sector.id || ''
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function loadTargets(): Promise<void> {
  if (!available) return
  loadingTargets.value = true
  targetNotice.value = ''
  try {
    const base = await bridge.apiBase()
    targetClient?.close()
    targetClient = createPetAgentClient(base)
    projects.value = (await targetClient.listProjects()).map(project => ({ id: project.id, name: project.name }))
    const initial = targetProjectId.value || projects.value[0]?.id || ''
    if (initial) await loadTargetSessions(initial)
  } catch (cause) {
    targetNotice.value = `会话列表读取失败：${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    loadingTargets.value = false
  }
}

async function loadTargetSessions(projectId: string): Promise<void> {
  targetProjectId.value = projectId
  if (!targetClient || !projectId) {
    sessions.value = []
    return
  }
  loadingTargets.value = true
  try {
    sessions.value = (await targetClient.listSessions(projectId))
      .filter(session => !session.internal)
      .map(session => ({ id: session.id, title: session.title }))
    if (!sessions.value.some(session => session.id === targetSessionId.value)) {
      targetSessionId.value = sessions.value[0]?.id || ''
    }
  } catch (cause) {
    targetNotice.value = `会话读取失败：${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    loadingTargets.value = false
  }
}

async function applyTarget(): Promise<void> {
  if (!targetProjectId.value || !targetSessionId.value) return
  saving.value = true
  targetNotice.value = ''
  try {
    await patchPingTarget({ projectId: targetProjectId.value, sessionId: targetSessionId.value })
    config.target = { projectId: targetProjectId.value, sessionId: targetSessionId.value }
    targetNotice.value = '已设为 Ping 目标；下一条 Ping 会进入该会话。'
    saved.value = true
    window.setTimeout(() => { saved.value = false }, 1500)
  } catch (cause) {
    targetNotice.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

let pending: PingPatch = {}
let saveTimer = 0
let revision = 0

function queue(patch: PingPatch): void {
  revision += 1
  pending = { ...pending, ...patch }
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => { void flush() }, 350)
}

async function flush(): Promise<void> {
  if (!Object.keys(pending).length) return
  const patch = pending
  const at = revision
  pending = {}
  saving.value = true
  error.value = ''
  try {
    const next = await patchPingConfig(patch)
    // 只把服务端确认后的 Ping 字段写回；避免把桌宠字段一起改掉。
    Object.assign(config, next)
    if (revision === at) {
      saved.value = true
      window.setTimeout(() => { saved.value = false }, 1500)
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

function setField<K extends keyof PingConfig>(key: K, value: PingConfig[K]): void {
  config[key] = value
  queue({ [key]: value } as PingPatch)
}

async function setEnabled(value: boolean): Promise<void> {
  config.enabled = value
  queue({ enabled: value })
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    // 立即生效：关闭时先注销热键，开启时先显示穿透窗口；完整热键由
    // Ping 页面收到 config-changed 后按最新配置重新注册。
    await invoke('pet_hotkey_set', { accelerator: value ? config.hotkey : null })
    if (value) await invoke('pet_ping_overlay_show')
    else await invoke('pet_ping_overlay_hide')
  } catch {
    // 浏览器预览没有 Tauri 窗口；配置仍然会落盘。
  }
}

function updateSectors(next: PingSectorConfig[]): void {
  config.sectors = next
  queue({ sectors: JSON.parse(JSON.stringify(next)) as PingSectorConfig[] })
}

function updateSelected(patch: Partial<PingSectorConfig>): void {
  if (!selected.value) return
  const next = config.sectors.map(sector => (
    sector.id === selected.value!.id ? { ...sector, ...patch } : sector
  ))
  updateSectors(next)
}

function selectNode(id: string): void {
  selectedId.value = id
  sandboxResult.value = ''
}

function newId(prefix = 'sector'): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 5)}`
}

function addRoot(): void {
  const sector: PingSectorConfig = {
    id: newId(),
    label: '新项',
    icon: '＋',
    kind: 'custom',
    color: '#B9C6DB',
    enabled: true,
  }
  updateSectors([...config.sectors, sector])
  selectedId.value = sector.id
}

function addChild(): void {
  const parent = selected.value
  const node = selectedNode.value
  if (!parent || !node) return
  if (node.depth >= PING_MAX_DEPTH) {
    error.value = `最多 ${PING_MAX_DEPTH} 级菜单；当前项已经是最后一级`
    return
  }
  const group = parent.subring || `sub-${parent.id}`
  const nextParent: PingSectorConfig = {
    ...parent,
    kind: parent.kind === 'subring' ? parent.kind : 'subring',
    subring: group,
  }
  const child: PingSectorConfig = {
    id: newId('item'),
    label: '子项',
    icon: '·',
    kind: 'custom',
    color: '#BFD2F5',
    enabled: true,
    group,
  }
  updateSectors([
    ...config.sectors.map(sector => (sector.id === parent.id ? nextParent : sector)),
    child,
  ])
  selectedId.value = child.id
}

function duplicateSelected(): void {
  const sector = selected.value
  if (!sector) return
  const copy: PingSectorConfig = {
    ...sector,
    id: newId(sector.kind),
    label: `${sector.label} 副本`,
  }
  const index = config.sectors.findIndex(item => item.id === sector.id)
  const next = [...config.sectors]
  next.splice(index + 1, 0, copy)
  updateSectors(next)
  selectedId.value = copy.id
}

function removeSelected(): void {
  const sector = selected.value
  if (!sector) return
  const ids = collectSubtreeIds(config.sectors, sector.id)
  const next = config.sectors.filter(item => !ids.has(item.id))
  updateSectors(next)
  selectedId.value = next[0]?.id || ''
}

function moveSelected(delta: -1 | 1): void {
  const sector = selected.value
  if (!sector) return
  const next = movePingSector(config.sectors, sector.id, delta)
  if (next === config.sectors) return
  updateSectors(next)
}

function onDragStart(id: string, event: DragEvent): void {
  dragId.value = id
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', id)
  }
}

function onDragOver(id: string, event: DragEvent): void {
  if (!dragId.value || dragId.value === id) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropTargetId.value = id
  const box = (event.currentTarget as HTMLElement).getBoundingClientRect()
  dropPosition.value = event.clientY >= box.top + box.height / 2 ? 'after' : 'before'
}

function onDragEnd(): void {
  dragId.value = ''
  dropTargetId.value = ''
}

function onDrop(targetId: string, event: DragEvent): void {
  event.preventDefault()
  const moving = dragId.value
  const reparent = event.ctrlKey || event.metaKey
  dragId.value = ''
  dropTargetId.value = ''
  if (!moving || moving === targetId) return
  if (reparent) {
    const result = reparentPingSector(config.sectors, moving, targetId)
    if (result.error) {
      error.value = result.error
      return
    }
    updateSectors(result.sectors)
  } else {
    const next = movePingSectorBeside(config.sectors, moving, targetId, dropPosition.value)
    if (next === config.sectors) {
      error.value = '只能在同一父级内拖动排序；按住 Ctrl 拖到某行可成为它的子项'
      return
    }
    updateSectors(next)
  }
  error.value = ''
  selectedId.value = moving
}

function setKind(value: PingSectorKind): void {
  if (!selected.value) return
  if (childCount.value > 0 && value !== 'subring') {
    error.value = '这个项已有子菜单；要改成普通动作请先删除它的子项，避免子项变成不可达的孤儿'
    return
  }
  const patch: Partial<PingSectorConfig> = { kind: value }
  if (value === 'subring' && !selected.value.subring) patch.subring = `sub-${selected.value.id}`
  updateSelected(patch)
}

function resetPrompt(): void {
  if (!selected.value) return
  const kind = selected.value.kind
  const prompt = kind === 'question'
    ? DEFAULT_PING_PROMPTS.question
    : kind === 'exclamation'
      ? DEFAULT_PING_PROMPTS.exclamation
      : kind === 'note'
        ? DEFAULT_PING_PROMPTS.note
        : ''
  updateSelected({ prompt })
}

function simulateArc(id: string): void {
  const sector = config.sectors.find(item => item.id === id)
  if (!sector) return
  selectedId.value = id
  // user:“模拟绝不发送真实 Agent 消息、审批或抢占桌面”+
  // (这里只展示实际会走的分支，不调用截图/网络/窗口。)
  sandboxResult.value = `沙盒预览：${sector.label} → ${pingActionLabel(sector)}${sector.prompt ? `；提示词「${sector.prompt}」` : ''}（未发送，未截图）`
}

function isSelectedArc(id: string): boolean {
  return selected.value?.id === id
}

const SELECTION_KEY = 'lamtools.core.settings.ping.selected'
function rememberSelection(): void {
  try { if (selectedId.value) localStorage.setItem(SELECTION_KEY, selectedId.value) } catch { /* 存储不可用 */ }
}
function restoreSelection(): void {
  try {
    const saved = localStorage.getItem(SELECTION_KEY) || ''
    if (saved && config.sectors.some(sector => sector.id === saved)) selectedId.value = saved
  } catch { /* 存储不可用 */ }
}
watch(selectedId, rememberSelection)

function applyDeepLink(objectId: string): void {
  if (!objectId || !config.sectors.some(sector => sector.id === objectId)) return
  selectedId.value = objectId
  void nextTick(() => {
    document.querySelector(`[data-ping-sector="${CSS.escape(objectId)}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  })
}

let unlisten: (() => void) | null = null
let offDeepLink: (() => void) | null = null
onMounted(() => {
  void load().then(() => {
    restoreSelection()
    applyDeepLink(consumeSettingsDeepLink('ping'))
    void loadTargets()
  })
  offDeepLink = onSettingsDeepLink('ping', applyDeepLink)
  if (!available) return
  void import('@tauri-apps/api/event').then(({ listen }) => {
    void listen('pet://config-changed', () => {
      // 自己保存时忽略广播，避免覆盖正在编辑但尚未 flush 的草稿。
      if (loading.value || saving.value || Object.keys(pending).length) return
      void load()
    }).then(off => { unlisten = off })
  }).catch(() => undefined)
})

onBeforeUnmount(() => {
  if (saveTimer) window.clearTimeout(saveTimer)
  // 切换设置页时也要把 350ms 防抖窗口里的最后改动写回，不能静默丢失。
  if (Object.keys(pending).length) void flush()
  targetClient?.close()
  unlisten?.()
  offDeepLink?.()
})
</script>

<template>
  <div class="ping-workbench">
    <header class="ping-workbench__head">
      <div>
        <h2>Ping 工作台</h2>
        <p>编辑一、二级同心扇环、提示词与本地动作；选择只在页面沙盒内生效，不会发送真实消息。</p>
      </div>
      <div class="ping-workbench__actions">
        <span v-if="saving" class="ping-state">正在保存…</span>
        <span v-else-if="saved" class="ping-state ping-state--ok">已保存</span>
        <label class="ping-toggle">
          <input
            type="checkbox"
            :checked="config.enabled"
            @change="setEnabled(($event.target as HTMLInputElement).checked)"
          >
          启用 Ping
        </label>
      </div>
    </header>

    <p v-if="!available" class="ping-hint">Ping 工作台仅在桌面版可用。</p>
    <p v-else-if="error" class="ping-error" role="alert">{{ error }}</p>

    <div v-if="available" class="ping-workbench__body">
      <aside class="ping-menu">
        <div class="ping-menu__head">
          <strong>菜单树</strong>
          <span>{{ enabledRootCount }} 一级 / {{ enabledTotal }} 启用</span>
        </div>
        <div class="ping-menu__list" role="tree">
          <button
            v-for="node in nodes"
            :key="node.sector.id"
            type="button"
            class="ping-menu__item"
            :data-ping-sector="node.sector.id"
            :class="{
              'is-selected': node.sector.id === selected?.id,
              'is-disabled': !node.sector.enabled,
              'is-dragging': dragId === node.sector.id,
              'is-drop-before': dropTargetId === node.sector.id && dropPosition === 'before',
              'is-drop-after': dropTargetId === node.sector.id && dropPosition === 'after',
            }"
            :style="{ paddingLeft: `${10 + (node.depth - 1) * 16}px` }"
            role="treeitem"
            draggable="true"
            @click="selectNode(node.sector.id)"
            @dragstart="onDragStart(node.sector.id, $event)"
            @dragover="onDragOver(node.sector.id, $event)"
            @drop="onDrop(node.sector.id, $event)"
            @dragend="onDragEnd"
          >
            <span class="ping-menu__icon" :style="{ color: node.sector.color }">{{ node.sector.icon || '·' }}</span>
            <span class="ping-menu__label">{{ node.sector.label }}</span>
            <span v-if="node.children.length" class="ping-menu__count">{{ node.children.length }}</span>
          </button>
          <div v-if="!nodes.length" class="ping-menu__empty">还没有 Ping 项，先添加一个。</div>
          <p class="ping-menu__hint">拖动排序；按住 Ctrl 拖到某行可成为它的子项（最多三级）。</p>
        </div>
        <div class="ping-menu__tools">
          <button type="button" class="btn btn--ghost" @click="addRoot">＋ 一级项</button>
          <button type="button" class="btn btn--ghost" :disabled="!selected || (selectedNode?.depth || 0) >= PING_MAX_DEPTH" @click="addChild">＋ 子项</button>
          <button type="button" class="btn btn--ghost" :disabled="!selected" @click="duplicateSelected">复制</button>
          <button type="button" class="btn btn--ghost" :disabled="!selected" @click="moveSelected(-1)">上移</button>
          <button type="button" class="btn btn--ghost" :disabled="!selected" @click="moveSelected(1)">下移</button>
          <button type="button" class="ping-danger" :disabled="!selected" @click="removeSelected">删除</button>
        </div>
      </aside>

      <section class="ping-preview">
        <div class="ping-preview__toolbar">
          <span>一级完整环 · 选中项子环</span>
          <span class="ping-preview__meta">{{ Math.max(0, geometry.bands.length - 1) }} 层子环</span>
          <select v-model="previewPresetId" class="ping-preview__preset" aria-label="模拟屏幕尺寸">
            <option v-for="preset in PREVIEW_PRESETS" :key="preset.id" :value="preset.id">{{ preset.label }}</option>
          </select>
          <select v-model.number="previewDpi" class="ping-preview__preset" aria-label="模拟系统缩放">
            <option :value="100">100%</option>
            <option :value="125">125%</option>
            <option :value="150">150%</option>
            <option :value="200">200%</option>
          </select>
        </div>
        <p v-if="previewClamped" class="ping-preview__warn">
          当前环半径 {{ config.radius }} 超出模拟可视区，预览按 {{ Math.round(previewLimit) }} 显示；真实桌面会按屏幕边缘自适应。
        </p>
        <div class="ping-preview__stage" :style="{ aspectRatio: `${previewPreset.width} / ${previewPreset.height}` }">
        <svg
          class="ping-preview__ring"
          :viewBox="`0 0 ${geometry.size} ${geometry.size}`"
          role="img"
          aria-label="Ping 环预览"
        >
          <circle
            :cx="geometry.cx"
            :cy="geometry.cy"
            :r="Math.max(20, geometry.radius - geometry.bandWidth / 2 - 8)"
            class="ping-preview__hub"
          />
          <g v-for="(band, bandIndex) in geometry.bands" :key="`band-${bandIndex}`">
            <path
              v-for="arc in band.arcs"
              :key="`${bandIndex}-${arc.id}`"
              :d="arc.path"
              class="ping-preview__arc"
              :class="{ 'is-selected': isSelectedArc(arc.id) }"
              :style="{ fill: arc.enabled ? arc.color : 'var(--border)' }"
              @pointerenter="sandboxRingOpen && (sandboxHoverId = arc.id)"
              @click="simulateArc(arc.id)"
            >
              <title>{{ arc.fullLabel }}（{{ pingActionLabel(config.sectors.find(item => item.id === arc.id) || {} as PingSectorConfig) }}）</title>
            </path>
          </g>
          <g>
            <text
              v-for="arc in selectedArcs"
              :key="`label-${arc.id}`"
              :x="arc.labelX"
              :y="arc.labelY"
              class="ping-preview__label"
              text-anchor="middle"
              dominant-baseline="middle"
              :transform="`rotate(${arc.rotation} ${arc.labelX} ${arc.labelY})`"
            >{{ arc.label }}</text>
          </g>
        </svg>
        </div>
        <div class="ping-preview__sim">
          <button type="button" class="btn btn--ghost" @click="sandboxRingOpen = true; sandboxResult = '模拟环已打开：移动鼠标选择，松键模拟执行'">{{ sandboxRingOpen ? '模拟环已打开' : '模拟按住快捷键' }}</button>
          <button type="button" class="btn" :disabled="!sandboxRingOpen" @click="simulateArc(sandboxHoverId || selected?.id || ''); sandboxRingOpen = false">模拟松键执行</button>
          <button type="button" class="btn btn--ghost" :disabled="!sandboxRingOpen" @click="sandboxRingOpen = false; sandboxHoverId = ''; sandboxResult = '已模拟取消，没有执行任何动作'">取消</button>
        </div>
        <div class="ping-preview__sandbox">
          <span>{{ sandboxResult || '点击任一扇区进行沙盒选择；这里不会截图、不会发送消息。' }}</span>
        </div>
      </section>

      <aside v-if="selected" class="ping-props">
        <div class="ping-props__head">
          <strong>当前项</strong>
          <span>第 {{ selectedNode?.depth || 1 }} 级</span>
        </div>
        <label class="ping-row">
          <span>名称</span>
          <input :value="selected.label" @input="updateSelected({ label: ($event.target as HTMLInputElement).value })">
        </label>
        <label class="ping-row">
          <span>图标</span>
          <input class="ping-row__icon" :value="selected.icon" maxlength="2" @input="updateSelected({ icon: ($event.target as HTMLInputElement).value })">
        </label>
        <label class="ping-row">
          <span>颜色</span>
          <input type="color" :value="selected.color" @input="updateSelected({ color: ($event.target as HTMLInputElement).value })">
        </label>
        <label class="ping-row">
          <span>行为</span>
          <select :value="selected.kind" @change="setKind(($event.target as HTMLSelectElement).value as PingSectorKind)">
            <option v-for="kind in KINDS" :key="kind.label" :value="kind.value">{{ kind.label }}</option>
          </select>
        </label>
        <label class="ping-row">
          <span>启用</span>
          <input type="checkbox" :checked="selected.enabled" @change="updateSelected({ enabled: ($event.target as HTMLInputElement).checked })">
        </label>
        <label v-if="selected.kind === 'custom'" class="ping-row">
          <span>本地动作</span>
          <select :value="selected.action || ''" @change="updateSelected({ action: ($event.target as HTMLSelectElement).value })">
            <option value="">未绑定</option>
            <option v-for="action in LOCAL_ACTIONS" :key="action.id" :value="action.id">{{ action.label }}</option>
          </select>
        </label>
        <label v-if="selected.kind === 'subring'" class="ping-row">
          <span>子菜单 ID</span>
          <input :value="selected.subring || ''" @input="updateSelected({ subring: ($event.target as HTMLInputElement).value })">
        </label>
        <label class="ping-row ping-row--column">
          <span>提示词</span>
          <textarea
            rows="4"
            :value="selected.prompt || ''"
            placeholder="留空则使用该行为的默认提示"
            @input="updateSelected({ prompt: ($event.target as HTMLTextAreaElement).value })"
          />
        </label>
        <button type="button" class="btn btn--ghost" @click="resetPrompt">恢复默认提示词</button>
        <p class="ping-hint">
          {{ pingActionLabel(selected) }}
          <span v-if="childCount"> · 已有 {{ childCount }} 个子项</span>
        </p>
      </aside>
    </div>

    <section v-if="available" class="ping-general">
      <article class="setting-card">
        <div class="subhead"><span class="muted subhead-title">快捷键与尺寸</span></div>
        <label class="ping-row">
          <span>快捷键（按住显示，松开执行）</span>
          <input :value="config.hotkey" @input="setField('hotkey', ($event.target as HTMLInputElement).value)">
        </label>
        <label class="ping-row">
          <span>环半径</span>
          <input type="number" min="60" max="420" :value="config.radius" @change="setField('radius', Number(($event.target as HTMLInputElement).value))">
        </label>
        <label class="ping-row">
          <span>环身宽度</span>
          <input type="number" min="4" max="48" :value="config.ringWidth" @change="setField('ringWidth', Number(($event.target as HTMLInputElement).value))">
        </label>
        <label class="ping-row">
          <span>标记动画时长（毫秒）</span>
          <input type="number" min="600" max="6000" step="100" :value="config.markerMs" @change="setField('markerMs', Number(($event.target as HTMLInputElement).value))">
        </label>
        <label class="ping-row">
          <span>「对话」自动附当前截图</span>
          <input type="checkbox" :checked="config.autoAttachScreenshot" @change="setField('autoAttachScreenshot', ($event.target as HTMLInputElement).checked)">
        </label>
        <label class="ping-row">
          <span>自动把「切换会话」固定到右侧</span>
          <input type="checkbox" :checked="config.autoPlaceSwitch !== false" @change="setField('autoPlaceSwitch', ($event.target as HTMLInputElement).checked)">
        </label>
        <p class="ping-hint">关闭后严格按菜单树顺序显示一级项，不再自动移动「切换会话」。</p>
      </article>

      <article class="setting-card">
        <div class="subhead"><span class="muted subhead-title">诊断</span></div>
        <p class="ping-hint">Ping：{{ config.enabled ? '已启用' : '已关闭' }} · 一级 {{ enabledRootCount }} 项 · 总启用 {{ enabledTotal }} 项 · 子项 {{ Math.max(0, config.sectors.length - enabledRootCount) }} 项</p>
        <p class="ping-hint">热键：{{ config.hotkey || '未设置' }} · 自动右侧切换会话：{{ config.autoPlaceSwitch !== false ? '开' : '关' }}</p>
        <p class="ping-hint">配置：<code>.lam/pet/config.json</code> 的 ping 领域（逻辑隔离写入，物理合并文件）。</p>
      </article>

      <article class="setting-card">
        <div class="subhead"><span class="muted subhead-title">目标会话（独立于桌宠）</span></div>
        <label class="ping-row">
          <span>项目</span>
          <select :value="targetProjectId" :disabled="loadingTargets" @change="loadTargetSessions(($event.target as HTMLSelectElement).value)">
            <option v-if="!projects.length" value="">暂无项目</option>
            <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
          </select>
        </label>
        <label class="ping-row">
          <span>会话</span>
          <select v-model="targetSessionId" :disabled="loadingTargets || !sessions.length">
            <option v-if="!sessions.length" value="">暂无会话</option>
            <option v-for="session in sessions" :key="session.id" :value="session.id">{{ session.title }}</option>
          </select>
        </label>
        <div class="ping-target-actions">
          <button type="button" class="btn" :disabled="saving || !targetProjectId || !targetSessionId" @click="applyTarget">设为 Ping 目标</button>
          <button type="button" class="btn btn--ghost" :disabled="loadingTargets" @click="loadTargets">刷新会话</button>
          <span class="ping-hint">项目 {{ config.target?.projectId || '未设置' }} · 会话 {{ config.target?.sessionId || '未设置' }}</span>
        </div>
        <p v-if="targetNotice" class="ping-hint">{{ targetNotice }}</p>
        <p class="ping-hint">只修改 Ping 绑定，不改变任何桌宠的默认会话；真实发送后打开 Sunday 主窗口并定位到这里。</p>
      </article>
    </section>

    <PingCaptureSandbox v-if="available" />
  </div>
</template>

<style scoped>
.ping-workbench {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 2px 28px;
}
.ping-workbench__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.ping-workbench__head h2 {
  margin: 0 0 4px;
  font-size: 16px;
}
.ping-workbench__head p {
  margin: 0;
  max-width: 720px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.ping-workbench__actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: none;
  font-size: 12px;
}
.ping-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ping-state { color: var(--muted); }
.ping-state--ok { color: var(--success, #4f9d69); }
.ping-error {
  margin: 0;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--danger, #c0392b) 40%, transparent);
  border-radius: 8px;
  color: var(--danger, #c0392b);
  font-size: 12px;
}
.ping-hint { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
.ping-workbench__body {
  display: grid;
  grid-template-columns: minmax(180px, 220px) minmax(320px, 1fr) minmax(240px, 300px);
  gap: 14px;
  align-items: stretch;
}
.ping-menu,
.ping-preview,
.ping-props {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel, var(--surface, transparent));
}
.ping-menu { display: flex; flex-direction: column; }
.ping-menu__head,
.ping-props__head,
.ping-preview__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.ping-menu__head span,
.ping-props__head span,
.ping-preview__meta { color: var(--muted); font-size: 11px; }
.ping-menu__list { flex: 1; max-height: 420px; overflow-y: auto; padding: 6px; }
.ping-menu__item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 5px 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.ping-menu__item:hover { background: color-mix(in srgb, var(--text) 6%, transparent); }
.ping-menu__item.is-selected { border-color: var(--accent, #6aa8ff); background: color-mix(in srgb, var(--accent, #6aa8ff) 12%, transparent); }
.ping-menu__item.is-disabled { opacity: 0.55; }
.ping-menu__item.is-dragging { opacity: 0.4; }
.ping-menu__item.is-drop-before { box-shadow: inset 0 2px 0 var(--accent, #6aa8ff); }
.ping-menu__item.is-drop-after { box-shadow: inset 0 -2px 0 var(--accent, #6aa8ff); }
.ping-menu__hint { margin: 6px 4px 0; color: var(--muted); font-size: 10px; line-height: 1.4; }
.ping-menu__icon { width: 18px; flex: none; text-align: center; }
.ping-menu__label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ping-menu__count { flex: none; color: var(--muted); font-size: 10px; }
.ping-menu__empty { padding: 12px; color: var(--muted); font-size: 12px; }
.ping-menu__tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px;
  border-top: 1px solid var(--border);
}
.ping-menu__tools .btn { padding: 3px 7px; font-size: 11px; }
.ping-danger {
  padding: 3px 7px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--danger, #c0392b);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.ping-preview { display: flex; flex-direction: column; }
.ping-preview__stage {
  width: 100%;
  max-height: 460px;
  display: grid;
  place-items: center;
  margin: 0 auto;
  overflow: hidden;
}
.ping-preview__ring {
  width: 100%;
  height: 100%;
  max-height: 460px;
  display: block;
  margin: 0 auto;
  cursor: pointer;
}
.ping-preview__preset {
  max-width: 145px;
  padding: 2px 5px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
  font-size: 10px;
}
.ping-preview__warn { margin: 4px 10px; color: var(--danger, #c0392b); font-size: 11px; line-height: 1.4; }
.ping-preview__hub { fill: color-mix(in srgb, var(--text) 8%, transparent); stroke: var(--border); }
.ping-preview__arc {
  stroke: var(--background, #fff);
  stroke-width: 1.5;
  opacity: 0.92;
  transition: opacity 120ms ease-out;
}
.ping-preview__arc:hover { opacity: 1; }
.ping-preview__arc.is-selected { stroke: var(--text); stroke-width: 2.5; opacity: 1; }
.ping-preview__label {
  fill: #0b0d12;
  font-size: 10px;
  font-weight: 600;
  pointer-events: none;
}
.ping-preview__sim {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 10px 4px;
}
.ping-preview__sim .btn { padding: 3px 8px; font-size: 11px; }
.ping-preview__sandbox {
  margin: 6px 10px 10px;
  padding: 7px 9px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}
.ping-props {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-bottom: 10px;
  overflow-y: auto;
  max-height: 520px;
}
.ping-props > *:not(.ping-props__head) { margin-left: 10px; margin-right: 10px; }
.ping-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}
.ping-row > span { flex: none; color: var(--muted); }
.ping-row input:not([type='checkbox']):not([type='color']),
.ping-row select,
.ping-row textarea {
  flex: 1;
  min-width: 0;
  padding: 4px 7px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
  font-size: 12px;
}
.ping-row__icon { max-width: 54px; text-align: center; }
.ping-row--column { flex-direction: column; align-items: stretch; }
.ping-general {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}
.ping-general .setting-card { margin: 0; }
.ping-target-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
@media (max-width: 1100px) {
  .ping-workbench__body { grid-template-columns: 1fr; }
  .ping-menu__list { max-height: 220px; }
  .ping-props { max-height: none; }
}
</style>
