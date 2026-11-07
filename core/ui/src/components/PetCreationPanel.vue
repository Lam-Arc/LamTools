<script setup lang="ts">
/**
 * 桌宠工作台的零代码创建入口。
 *
 * user:“普通用户无需写 JSON、准备压缩包、安装 Blender，即能用一张图片创建
 * 可运行桌宠；上传多张图即可定义动作”+
 * (浏览器文件选择/拖放 → 自动推断动作 → 原子写角色包 → 追加配置 → 打开桌面。
 *  不要求用户理解 pet.json、ZIP 或 Blender。)
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { buildPetCreationPlan, type CreationFile } from '@/pet/creation.ts'
import { clearCreationDraft, loadCreationDraft, saveCreationDraft } from '@/pet/creationDraft.ts'
import { hasPetConfigAccess, updatePetConfig } from '@/pet/configFile.ts'
import { writePackBundle } from '@/pet/bridge.ts'
import type { PetRecordConfig } from '@/pet/config.ts'

const props = defineProps<{ records: PetRecordConfig[] }>()
const emit = defineEmits<{ created: [record: PetRecordConfig] }>()

const available = hasPetConfigAccess()
const name = ref('')
const files = ref<CreationFile[]>([])
const thumbs = ref<{ name: string; url: string }[]>([])
const loadingFiles = ref(false)
const creating = ref(false)
const error = ref('')
const notice = ref('')

let draftTimer = 0

function mimeForName(value: string): string {
  const ext = value.split('.').pop()?.toLowerCase() || ''
  if (ext === 'jpg' || ext === 'jpeg') return 'image/jpeg'
  if (ext === 'webp') return 'image/webp'
  if (ext === 'gif') return 'image/gif'
  if (ext === 'bmp') return 'image/bmp'
  return 'image/png'
}

function thumbFor(file: CreationFile): string {
  const copy = new Uint8Array(file.bytes)
  return URL.createObjectURL(new Blob([copy.buffer as ArrayBuffer], { type: mimeForName(file.name) }))
}

async function persistDraft(): Promise<void> {
  if (!available || files.value.length === 0) return
  try {
    await saveCreationDraft({ name: name.value, files: files.value, updatedAt: Date.now() })
  } catch {
    // 草稿恢复是保险，不是发布前置条件；存储失败不阻塞创建。
  }
}

function scheduleDraftSave(): void {
  if (draftTimer) window.clearTimeout(draftTimer)
  draftTimer = window.setTimeout(() => { void persistDraft() }, 500)
}

async function restoreDraft(): Promise<void> {
  if (!available) return
  try {
    const draft = await loadCreationDraft()
    if (!draft || draft.files.length === 0) return
    files.value = draft.files
    name.value = draft.name || draft.files[0].name.replace(/\.[^.]+$/, '')
    thumbs.value = draft.files.map(file => ({ name: file.name, url: thumbFor(file) }))
    notice.value = '已恢复上次未完成的创建草稿'
  } catch {
    // 没有草稿/数据库不可用都按空白创建处理。
  }
}

const plan = computed(() => buildPetCreationPlan({ name: name.value, files: files.value }))
const ready = computed(() => available && files.value.length > 0 && plan.value.errors.length === 0)

const previewIndex = ref(0)
let previewTimer = 0

const idleClip = computed(() => plan.value.actions.idle)
const idleSources = computed<string[]>(() => {
  const clip = idleClip.value
  if (!clip) return []
  if (clip.type === 'frames') return clip.sources
  return clip.type === 'static' || clip.type === 'spritesheet' || clip.type === 'model' ? [clip.source] : []
})
const previewSource = computed(() => idleSources.value[previewIndex.value % Math.max(1, idleSources.value.length)] || '')
const previewUrl = computed(() => thumbs.value.find(thumb => thumb.name === previewSource.value)?.url || thumbs.value[0]?.url || '')

function restartPreview(): void {
  if (previewTimer) window.clearInterval(previewTimer)
  previewTimer = 0
  previewIndex.value = 0
  if (idleSources.value.length <= 1) return
  previewTimer = window.setInterval(() => {
    previewIndex.value = (previewIndex.value + 1) % idleSources.value.length
  }, 160)
}

watch(idleSources, restartPreview, { immediate: true })

function clipSummary(clip: unknown): string {
  if (!clip || typeof clip !== 'object') return '未绑定资源'
  const value = clip as { type?: string; sources?: string[]; frameCount?: number; source?: string; skin?: string }
  if (value.type === 'frames') return `${value.sources?.length || 0} 帧`
  if (value.type === 'spritesheet') return `${value.frameCount || 0} 帧图集`
  if (value.type === 'blocky') return `方块人：${value.skin || '默认皮肤'}`
  return value.source || '未绑定资源'
}

function revokeThumbs(): void {
  for (const thumb of thumbs.value) URL.revokeObjectURL(thumb.url)
  thumbs.value = []
}

async function readImage(file: File): Promise<{ entry: CreationFile; thumb: string } | null> {
  const imageLike = /^image\/(png|jpeg|webp|gif|bmp)$/i.test(file.type)
    || /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name)
  if (!imageLike) return null
  const bytes = new Uint8Array(await file.arrayBuffer())
  const url = URL.createObjectURL(file)
  try {
    const size = await new Promise<{ width: number; height: number }>((resolve, reject) => {
      const image = new Image()
      image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
      image.onerror = () => reject(new Error(`无法读取图片：${file.name}`))
      image.src = url
    })
    return {
      entry: { name: file.name, size: file.size, bytes, width: size.width, height: size.height },
      thumb: url,
    }
  } catch (cause) {
    URL.revokeObjectURL(url)
    throw cause
  }
}

async function acceptFiles(list: FileList | File[]): Promise<void> {
  if (!available) return
  loadingFiles.value = true
  error.value = ''
  notice.value = ''
  const nextFiles: CreationFile[] = []
  const nextThumbs: { name: string; url: string }[] = []
  try {
    for (const file of Array.from(list)) {
      const read = await readImage(file)
      if (!read) {
        error.value = `${file.name} 不是支持的图片格式（PNG/JPG/WEBP/GIF/BMP）`
        continue
      }
      nextFiles.push(read.entry)
      nextThumbs.push({ name: file.name, url: read.thumb })
    }
    if (nextFiles.length === 0) return
    revokeThumbs()
    files.value = nextFiles
    thumbs.value = nextThumbs
    if (!name.value.trim()) {
      name.value = nextFiles[0].name.replace(/\.[^.]+$/, '')
    }
    void persistDraft()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loadingFiles.value = false
  }
}

function onPick(event: Event): void {
  const input = event.target as HTMLInputElement
  if (input.files) void acceptFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent): void {
  if (event.dataTransfer?.files?.length) void acceptFiles(event.dataTransfer.files)
}

function clearSelection(): void {
  revokeThumbs()
  files.value = []
  error.value = ''
  notice.value = ''
  void clearCreationDraft().catch(() => undefined)
}

/** 与 Rust sanitize_pack_id 同语义：用于避免同名角色互相覆盖角色包。 */
function packIdFor(name: string): string {
  let out = ''
  for (const char of name.trim()) {
    if (/[a-zA-Z0-9._-]/.test(char)) out += char.toLowerCase()
    else if (/\s/.test(char)) out += '-'
    if (out.length >= 48) break
  }
  return out.replace(/^[-.]+|[-.]+$/g, '')
}

function uniquePackName(base: string): string {
  const usedNames = new Set(props.records.map(record => record.name.trim().toLowerCase()))
  const usedPacks = new Set(props.records.map(record => (record.packId || '').toLowerCase()))
  if (!usedNames.has(base.trim().toLowerCase()) && !usedPacks.has(packIdFor(base))) return base
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${base} ${index}`
    if (!usedNames.has(candidate.toLowerCase()) && !usedPacks.has(packIdFor(candidate))) return candidate
  }
  return `${base} ${Date.now().toString(36)}`
}

async function create(): Promise<void> {
  if (!ready.value || creating.value) return
  creating.value = true
  error.value = ''
  notice.value = ''
  try {
    const currentPlan = plan.value
    const pack = await writePackBundle(uniquePackName(currentPlan.name), currentPlan.entries)
    const record: PetRecordConfig = {
      id: `${pack.id}-${Date.now().toString(36)}`,
      name: currentPlan.name,
      packId: pack.id,
      scale: 1,
      facing: 1,
      radius: Math.max(10, Math.round(Math.min(currentPlan.spriteWidth, currentPlan.spriteHeight) * 0.38)),
      visible: true,
      actions: currentPlan.actions,
      spriteWidth: currentPlan.spriteWidth,
      spriteHeight: currentPlan.spriteHeight,
      hitboxes: currentPlan.hitboxes,
      physics: {},
      behavior: {},
      importWarnings: currentPlan.warnings,
    }
    const config = await updatePetConfig(latest => ({
      pets: [...latest.pets, record],
      presetInstalled: true,
    }))
    if (config.enabled) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('pet_overlay_open')
      } catch {
        notice.value = '角色已保存；桌宠窗口下次打开时会显示它。'
      }
    }
    notice.value = notice.value || `已创建「${record.name}」，桌宠窗口会立即加载它。`
    emit('created', record)
    clearSelection()
    name.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    creating.value = false
  }
}

onMounted(() => {
  void restoreDraft()
})

onBeforeUnmount(() => {
  if (previewTimer) window.clearInterval(previewTimer)
  if (draftTimer) window.clearTimeout(draftTimer)
  void persistDraft()
  revokeThumbs()
})
</script>

<template>
  <section class="pet-create">
    <header class="pet-create__head">
      <div>
        <h3>创建桌宠</h3>
        <p>选择一张图片直接创建；多张图片会按文件名自动识别待机、行走、跳跃等动作，也可以顺序组成动画。</p>
      </div>
      <span v-if="loadingFiles" class="pet-create__state">正在读取图片…</span>
    </header>

    <p v-if="!available" class="pet-create__hint">创建功能仅在桌面版可用。</p>
    <template v-else>
      <div
        class="pet-create__drop"
        tabindex="0"
        role="button"
        aria-label="选择或拖入桌宠图片"
        @click="($refs.picker as HTMLInputElement)?.click()"
        @keydown.enter="($refs.picker as HTMLInputElement)?.click()"
        @dragover.prevent
        @drop.prevent="onDrop"
      >
        <input
          ref="picker"
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
          multiple
          hidden
          @change="onPick"
        >
        <strong>选择图片或拖到这里</strong>
        <span>PNG / JPG / WEBP / GIF / BMP；多张图片按文件名分组为动作</span>
      </div>

      <div v-if="thumbs.length" class="pet-create__assets">
        <figure v-for="thumb in thumbs" :key="thumb.url" class="pet-create__thumb">
          <img :src="thumb.url" :alt="thumb.name">
          <figcaption :title="thumb.name">{{ thumb.name }}</figcaption>
        </figure>
      </div>

      <div class="pet-create__form">
        <label>
          <span>角色名称</span>
          <input v-model="name" type="text" placeholder="例如：我的鲸鱼娘" @input="scheduleDraftSave">
        </label>
        <div class="pet-create__actions">
          <button type="button" class="btn" :disabled="!ready || creating" @click="create">
            {{ creating ? '正在创建…' : '创建并放到桌面' }}
          </button>
          <button v-if="files.length" type="button" class="btn btn--ghost" :disabled="creating" @click="clearSelection">清空</button>
        </div>
      </div>

      <div v-if="previewUrl" class="pet-create__preview" aria-label="待机动画预览">
        <img :src="previewUrl" :alt="plan.name">
        <span>{{ idleSources.length > 1 ? `待机预览 ${previewIndex + 1}/${idleSources.length}` : '预览' }}</span>
      </div>

      <div v-if="files.length" class="pet-create__plan">
        <div class="pet-create__plan-head">
          <strong>识别到 {{ Object.keys(plan.actions).length }} 个动作</strong>
          <span>{{ plan.spriteWidth }}×{{ plan.spriteHeight }} · {{ files.length }} 张图</span>
        </div>
        <ul>
          <li v-for="(clip, actionId) in plan.actions" :key="actionId">
            <strong>{{ actionId }}</strong>
            <span>{{ clipSummary(clip) }}</span>
          </li>
        </ul>
      </div>

      <p v-if="error" class="pet-create__error" role="alert">{{ error }}</p>
      <p v-if="notice" class="pet-create__notice">{{ notice }}</p>
      <p v-for="warning in plan.warnings" :key="warning" class="pet-create__warning">{{ warning }}</p>
    </template>
  </section>
</template>

<style scoped>
.pet-create {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel, var(--surface, transparent));
}
.pet-create__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.pet-create__head h3 {
  margin: 0 0 3px;
  font-size: 14px;
}
.pet-create__head p {
  margin: 0;
  max-width: 720px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
.pet-create__state { flex: none; color: var(--muted); font-size: 11px; }
.pet-create__hint { margin: 0; color: var(--muted); font-size: 12px; }
.pet-create__drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 92px;
  padding: 14px;
  border: 1px dashed var(--border);
  border-radius: 9px;
  color: var(--muted);
  font-size: 12px;
  text-align: center;
  cursor: pointer;
}
.pet-create__drop strong { color: var(--text); font-size: 13px; }
.pet-create__drop:hover { border-color: var(--accent, #6aa8ff); }
.pet-create__assets {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}
.pet-create__thumb {
  flex: none;
  width: 86px;
  margin: 0;
  text-align: center;
}
.pet-create__thumb img {
  width: 86px;
  height: 86px;
  object-fit: contain;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--control);
}
.pet-create__thumb figcaption {
  margin-top: 3px;
  overflow: hidden;
  color: var(--muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pet-create__form {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
}
.pet-create__form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.pet-create__form input {
  width: 240px;
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--control);
  color: var(--control-text);
}
.pet-create__actions { display: flex; gap: 8px; }
.pet-create__preview {
  position: relative;
  align-self: flex-start;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  min-height: 80px;
}
.pet-create__preview img {
  max-width: 240px;
  max-height: 180px;
  object-fit: contain;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--control);
}
.pet-create__preview span { color: var(--muted); font-size: 10px; }
.pet-create__plan {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12px;
}
.pet-create__plan-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: var(--muted);
  font-size: 11px;
}
.pet-create__plan-head strong { color: var(--text); font-size: 12px; }
.pet-create__plan ul {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 4px 12px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}
.pet-create__plan li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.pet-create__plan li span {
  overflow: hidden;
  color: var(--muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pet-create__error { margin: 0; color: var(--danger, #c0392b); font-size: 12px; }
.pet-create__notice { margin: 0; color: var(--success, #4f9d69); font-size: 12px; }
.pet-create__warning { margin: 0; color: var(--muted); font-size: 11px; }
</style>
