<script setup lang="ts">
/**
 * 单只桌宠的动作与命中区编辑。
 *
 * user:“上传多张图即可定义动作；可自由增加‘挥手’等自定义表现动作”+
 * “表现动作可绑定点击/双击指定身体 Hitbox”+
 * (图片写到角色包后更新同一份配置；不执行脚本，也不新增物理能力。
 *  命中区只改 action/doubleAction 指针，不改变物理 AABB。)
 */
import { computed, ref } from 'vue'
import type { PetHitbox } from '@/pet/engine/sprite.ts'
import { DEFAULT_BEHAVIOR } from '@/pet/engine/behavior.ts'
import type { PetRecordConfig } from '@/pet/config.ts'
import { MAX_ASSET_BYTES } from '@/pet/assets/importer.ts'
import { updatePetConfig } from '@/pet/configFile.ts'
import { writePackAsset } from '@/pet/bridge.ts'
import { actionRemovalError, clipForSources, slugActionName, uniqueActionId } from '@/pet/actionEditing.ts'

const props = defineProps<{ record: PetRecordConfig }>()
const emit = defineEmits<{ changed: [] }>()

const saving = ref(false)
const error = ref('')
const notice = ref('')
const newActionName = ref('')
const replaceTarget = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

const actionRows = computed(() => Object.entries(props.record.actions).map(([id, clip]) => {
  if (!clip) return { id, type: 'unknown', source: '未绑定资源', fps: 0, loop: true }
  if (clip.type === 'frames') {
    return {
      id,
      type: clip.type,
      source: `${clip.sources.length} 帧：${clip.sources[0] || ''}${clip.sources.length > 1 ? ' …' : ''}`,
      fps: clip.fps,
      loop: clip.loop !== false,
    }
  }
  if (clip.type === 'spritesheet') {
    return {
      id,
      type: clip.type,
      source: `${clip.frameCount} 帧图集：${clip.source}`,
      fps: clip.fps,
      loop: clip.loop !== false,
    }
  }
  if (clip.type === 'blocky') {
    return { id, type: clip.type, source: `方块人：${clip.skin || '默认皮肤'}`, fps: 0, loop: true }
  }
  return {
    id,
    type: clip.type,
    source: (clip as { source?: string }).source || '',
    fps: 0,
    loop: true,
  }
}))
const actionIds = computed(() => Object.keys(props.record.actions))
const behavior = computed(() => ({ ...DEFAULT_BEHAVIOR, ...props.record.behavior }))
function stableActionId(base: string): string {
  return uniqueActionId(actionIds.value, base)
}

async function readImages(files: FileList): Promise<{ rel: string; bytes: Uint8Array }[]> {
  const entries: { rel: string; bytes: Uint8Array }[] = []
  const stamp = Date.now().toString(36)
  let index = 0
  for (const file of Array.from(files)) {
    const imageLike = /^image\/(png|jpeg|webp|gif|bmp)$/i.test(file.type)
      || /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name)
    if (!imageLike) {
      throw new Error(`${file.name} 不是支持的图片格式`)
    }
    if (file.size > MAX_ASSET_BYTES) throw new Error(`${file.name} 超过单文件上限`)
    const ext = (file.name.split('.').pop() || 'png').toLowerCase().replace(/[^a-z0-9]/g, '')
    const rel = `actions/${slugActionName(actionIdForWrite.value)}-${stamp}-${index}.${ext}`
    entries.push({ rel, bytes: new Uint8Array(await file.arrayBuffer()) })
    index += 1
  }
  return entries
}

const actionIdForWrite = ref('')

async function bindFiles(actionId: string, files: FileList): Promise<void> {
  const packId = props.record.packId
  if (!packId) {
    error.value = '这个角色没有角色包目录，无法新增动作资源'
    return
  }
  actionIdForWrite.value = actionId
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const entries = await readImages(files)
    if (entries.length === 0) return
    for (const entry of entries) await writePackAsset(packId, entry.rel, entry.bytes)
    const clip = clipForSources(entries.map(entry => entry.rel))
    await updatePetConfig(latest => ({
      pets: latest.pets.map(record => (
        record.id === props.record.id
          ? { ...record, actions: { ...record.actions, [actionId]: clip } }
          : record
      )),
    }))
    notice.value = `已绑定 ${entries.length} 张图片到「${actionId}」`
    emit('changed')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

function pickFor(actionId: string): void {
  replaceTarget.value = actionId
  fileInput.value?.click()
}

function onFilePicked(event: Event): void {
  const input = event.target as HTMLInputElement
  if (input.files && replaceTarget.value) void bindFiles(replaceTarget.value, input.files)
  input.value = ''
}

function addAction(): void {
  const label = newActionName.value.trim()
  if (!label) return
  const id = stableActionId(label.startsWith('custom') ? slugActionName(label) : `custom-${slugActionName(label)}`)
  replaceTarget.value = id
  fileInput.value?.click()
  newActionName.value = ''
}

async function removeAction(actionId: string): Promise<void> {
  const blocked = actionRemovalError(actionId, props.record.actions, props.record.hitboxes)
  if (blocked) {
    error.value = blocked
    return
  }
  saving.value = true
  try {
    await updatePetConfig(latest => ({
      pets: latest.pets.map(record => {
        if (record.id !== props.record.id) return record
        const actions = { ...record.actions }
        delete actions[actionId]
        return { ...record, actions }
      }),
    }))
    emit('changed')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

async function updateClip(actionId: string, patch: Record<string, unknown>): Promise<void> {
  saving.value = true
  try {
    await updatePetConfig(latest => ({
      pets: latest.pets.map(record => {
        if (record.id !== props.record.id) return record
        const clip = record.actions[actionId]
        if (!clip) return record
        return {
          ...record,
          actions: { ...record.actions, [actionId]: { ...clip, ...patch } as typeof clip },
        }
      }),
    }))
    emit('changed')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

async function updateBehavior(patch: Record<string, unknown>): Promise<void> {
  saving.value = true
  try {
    await updatePetConfig(latest => ({
      pets: latest.pets.map(record => (
        record.id === props.record.id
          ? { ...record, behavior: { ...record.behavior, ...patch } }
          : record
      )),
    }))
    emit('changed')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

async function patchHitboxes(next: PetHitbox[]): Promise<void> {
  saving.value = true
  try {
    await updatePetConfig(latest => ({
      pets: latest.pets.map(record => (
        record.id === props.record.id ? { ...record, hitboxes: next } : record
      )),
    }))
    emit('changed')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

function clamp01(value: number, fallback: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : fallback
}

function updateHitbox(index: number, patch: Partial<PetHitbox>): void {
  const next = props.record.hitboxes.map((hitbox, at) => {
    if (at !== index) return hitbox
    const merged = { ...hitbox, ...patch }
    const width = Math.min(1, Math.max(0.02, clamp01(merged.width, hitbox.width)))
    const height = Math.min(1, Math.max(0.02, clamp01(merged.height, hitbox.height)))
    return {
      ...merged,
      width,
      height,
      x: Math.min(1 - width, clamp01(merged.x, hitbox.x)),
      y: Math.min(1 - height, clamp01(merged.y, hitbox.y)),
    }
  })
  void patchHitboxes(next)
}

function addHitbox(): void {
  const next: PetHitbox = {
    id: `part-${Date.now().toString(36)}`,
    name: '新部位',
    x: 0.2,
    y: 0.2,
    width: 0.6,
    height: 0.6,
    action: 'interact',
    doubleAction: 'jump_happy',
    enabled: true,
  }
  void patchHitboxes([...props.record.hitboxes, next])
}

function removeHitbox(index: number): void {
  if (props.record.hitboxes.length <= 1) return
  void patchHitboxes(props.record.hitboxes.filter((_, at) => at !== index))
}
</script>

<template>
  <div class="pet-action-panel">
    <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/bmp" multiple hidden @change="onFilePicked">

    <div class="pet-action-panel__head">
      <strong>动作</strong>
      <span v-if="saving">正在保存…</span>
      <span v-if="notice" class="is-ok">{{ notice }}</span>
    </div>
    <p v-if="!record.packId" class="pet-action-panel__hint">这个角色没有角色包目录，不能新增图片动作。</p>
    <div v-else class="pet-action-panel__add">
      <input v-model="newActionName" type="text" placeholder="新动作名称，例如：挥手">
      <button type="button" class="btn btn--ghost" :disabled="!newActionName.trim() || saving" @click="addAction">选择图片并新增</button>
    </div>

    <ul class="pet-action-panel__list">
      <li v-for="action in actionRows" :key="action.id">
        <code>{{ action.id }}</code>
        <span :title="action.source">{{ action.type }} · {{ action.source || '未绑定资源' }}</span>
        <button type="button" :disabled="!record.packId || saving" @click="pickFor(action.id)">绑定/替换</button>
        <button type="button" class="is-danger" :disabled="saving" @click="removeAction(action.id)">移除</button>
        <div v-if="action.type === 'frames' || action.type === 'spritesheet'" class="pet-action-panel__playback">
          <label>
            FPS
            <input
              type="number" min="1" max="60"
              :value="action.fps"
              @change="updateClip(action.id, { fps: Number(($event.target as HTMLInputElement).value) })"
            >
          </label>
          <label>
            <input
              type="checkbox"
              :checked="action.loop"
              @change="updateClip(action.id, { loop: ($event.target as HTMLInputElement).checked })"
            >
            循环
          </label>
        </div>
      </li>
    </ul>
    <p v-if="error" class="pet-action-panel__error" role="alert">{{ error }}</p>

    <div class="pet-action-panel__head">
      <strong>命中区</strong>
      <button type="button" class="btn btn--ghost" :disabled="saving" @click="addHitbox">＋ 部位</button>
    </div>
    <p class="pet-action-panel__hint">画出来的点击/穿透区域；物理碰撞仍由角色判定框决定，二者互不改写。</p>
    <div v-for="(hitbox, index) in record.hitboxes" :key="hitbox.id" class="pet-hitbox-row">
      <input
        class="pet-hitbox-row__name"
        :value="hitbox.name"
        @change="updateHitbox(index, { name: ($event.target as HTMLInputElement).value })"
      >
      <label>
        点击
        <select :value="hitbox.action" @change="updateHitbox(index, { action: ($event.target as HTMLSelectElement).value })">
          <option v-for="id in actionIds" :key="`click-${id}`" :value="id">{{ id }}</option>
        </select>
      </label>
      <label>
        双击
        <select :value="hitbox.doubleAction || ''" @change="updateHitbox(index, { doubleAction: ($event.target as HTMLSelectElement).value })">
          <option value="">同点击</option>
          <option v-for="id in actionIds" :key="`double-${id}`" :value="id">{{ id }}</option>
        </select>
      </label>
      <label class="pet-hitbox-row__enabled">
        <input type="checkbox" :checked="hitbox.enabled" @change="updateHitbox(index, { enabled: ($event.target as HTMLInputElement).checked })">
        启用
      </label>
      <button type="button" class="is-danger" :disabled="record.hitboxes.length <= 1 || saving" @click="removeHitbox(index)">删除</button>
      <div class="pet-hitbox-geometry">
        <label>X <input type="number" min="0" max="1" step="0.01" :value="hitbox.x" @change="updateHitbox(index, { x: Number(($event.target as HTMLInputElement).value) })"></label>
        <label>Y <input type="number" min="0" max="1" step="0.01" :value="hitbox.y" @change="updateHitbox(index, { y: Number(($event.target as HTMLInputElement).value) })"></label>
        <label>宽 <input type="number" min="0.02" max="1" step="0.01" :value="hitbox.width" @change="updateHitbox(index, { width: Number(($event.target as HTMLInputElement).value) })"></label>
        <label>高 <input type="number" min="0.02" max="1" step="0.01" :value="hitbox.height" @change="updateHitbox(index, { height: Number(($event.target as HTMLInputElement).value) })"></label>
      </div>
    </div>

    <div class="pet-action-panel__head">
      <strong>自主行为</strong>
      <label class="pet-behavior-enabled">
        <input type="checkbox" :checked="behavior.enabled" @change="updateBehavior({ enabled: ($event.target as HTMLInputElement).checked })">
        启用
      </label>
    </div>
    <div class="pet-behavior-grid">
      <label>
        <span>活动频率 {{ Math.round(behavior.activity * 100) }}%</span>
        <input type="range" min="0" max="1" step="0.05" :value="behavior.activity" @change="updateBehavior({ activity: Number(($event.target as HTMLInputElement).value) })">
      </label>
      <label>
        <span>休息倾向 {{ Math.round(behavior.restChance * 100) }}%</span>
        <input type="range" min="0" max="1" step="0.05" :value="behavior.restChance" @change="updateBehavior({ restChance: Number(($event.target as HTMLInputElement).value) })">
      </label>
      <label>
        <span>跟随鼠标倾向 {{ Math.round(behavior.mouseBias * 100) }}%</span>
        <input type="range" min="0" max="1" step="0.05" :value="behavior.mouseBias" @change="updateBehavior({ mouseBias: Number(($event.target as HTMLInputElement).value) })">
      </label>
      <label>
        <span>活动半径 {{ Math.round(behavior.exploreRadius) }}px</span>
        <input type="range" min="120" max="2400" step="40" :value="behavior.exploreRadius" @change="updateBehavior({ exploreRadius: Number(($event.target as HTMLInputElement).value) })">
      </label>
    </div>
  </div>
</template>

<style scoped>
.pet-action-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12px;
}
.pet-action-panel__head {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  font-size: 11px;
}
.pet-action-panel__head strong { color: var(--text); font-size: 12px; }
.pet-action-panel__head .is-ok { color: var(--success, #4f9d69); }
.pet-action-panel__add { display: flex; gap: 8px; }
.pet-action-panel__add input {
  flex: 1;
  min-width: 0;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
}
.pet-action-panel__list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.pet-action-panel__list li {
  display: grid;
  grid-template-columns: minmax(90px, 130px) minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  padding: 3px 5px;
  border-radius: 5px;
  background: color-mix(in srgb, var(--text) 4%, transparent);
}
.pet-action-panel__playback {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 2px 0 3px;
  color: var(--muted);
  font-size: 11px;
}
.pet-action-panel__playback label { display: inline-flex; align-items: center; gap: 4px; }
.pet-action-panel__playback input[type='number'] {
  width: 54px;
  padding: 2px 5px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
}
.pet-action-panel__list code { font-size: 11px; }
.pet-action-panel__list span {
  overflow: hidden;
  color: var(--muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pet-action-panel__list button,
.pet-hitbox-row button {
  padding: 2px 6px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.pet-action-panel__list button.is-danger,
.pet-hitbox-row button.is-danger { color: var(--danger, #c0392b); border-color: transparent; }
.pet-action-panel__hint { margin: 0; color: var(--muted); font-size: 11px; line-height: 1.45; }
.pet-action-panel__error { margin: 0; color: var(--danger, #c0392b); font-size: 11px; }
.pet-hitbox-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.pet-hitbox-row__name {
  width: 100px;
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
}
.pet-hitbox-row label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--muted);
  font-size: 11px;
}
.pet-hitbox-geometry {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  width: 100%;
  padding: 2px 0;
  color: var(--muted);
  font-size: 11px;
}
.pet-hitbox-geometry label { display: inline-flex; align-items: center; gap: 3px; }
.pet-hitbox-geometry input {
  width: 58px;
  padding: 2px 4px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
}
.pet-behavior-enabled { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); }
.pet-behavior-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 6px 14px;
}
.pet-behavior-grid label { display: flex; flex-direction: column; gap: 2px; color: var(--muted); font-size: 11px; }
.pet-behavior-grid input[type='range'] { width: 100%; }
.pet-hitbox-row select {
  padding: 3px 5px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--control);
  color: var(--control-text);
  font: inherit;
  font-size: 11px;
}
</style>
