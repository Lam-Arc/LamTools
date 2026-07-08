<template>
  <div class="session-sidebar-content">
    <div v-if="projectGroups.length === 0" class="sidebar-empty">
      <slot name="empty">暂无内容，创建一个开始。</slot>
    </div>

    <section
      v-for="group in projectGroups"
      :key="group.id"
      class="project-block"
      :class="{ active: isGroupActive(group) }"
    >
      <div class="project-top">
        <div class="project-btns">
          <!-- Per-project new session -->
          <button
            v-if="allowProjectNewSession"
            class="project-action add"
            :title="`在 ${group.name} 中新建会话`"
            :aria-label="`在 ${group.name} 中新建会话`"
            @click.stop="emit('new-session', group.id)"
          >+</button>
          <!-- Fold / expand -->
          <button
            v-if="group.sessions.length > projectSessionLimit && projectSessionLimit > 0"
            class="project-action fold"
            :title="groupExpanded[group.id] ? '折叠会话列表' : '展开全部会话'"
            :aria-label="groupExpanded[group.id] ? '折叠会话列表' : '展开全部会话'"
            @click.stop="toggleGroupExpand(group.id)"
          >
            {{ groupExpanded[group.id] ? '−' : '…' }}
          </button>
          <!-- Delete project -->
          <button
            v-if="allowProjectDelete"
            class="project-action remove"
            title="删除项目"
            :aria-label="`删除 ${group.name}`"
            @click.stop="emit('delete-project', group.id)"
          >×</button>
        </div>
        <div
          class="project-name"
          :class="{ clickable: allowProjectClick }"
          @click="allowProjectClick && emit('select-project', group.id)"
          @contextmenu.prevent="allowProjectContextMenu && emit('project-context-menu', group.id)"
        >
          <strong>{{ group.name }}</strong>
          <span v-if="group.workRoot" class="work-root">{{ group.workRoot }}</span>
          <span v-else class="work-root">{{ group.sessions.length }} 个会话</span>
        </div>
      </div>

      <div class="conversation-list">
        <div
          v-for="s in visibleSessions(group)"
          :key="s.id"
          class="conversation"
          :class="{ active: s.id === activeSessionId }"
          role="button"
          tabindex="0"
          :aria-label="`打开会话 ${s.title || s.id.slice(0, 8)}`"
          @click.stop="emit('select-session', s.id)"
          @keydown.enter.prevent.stop="emit('select-session', s.id)"
          @keydown.space.prevent.stop="emit('select-session', s.id)"
        >
          <span class="conversation-dot">{{ sessionOrdinal(group, s) }}</span>
          <span class="conversation-main">
            <strong
              v-if="renamingId !== s.id"
              @click.stop="startRename(s)"
            >{{ s.title || `Session ${s.id.slice(0, 8)}` }}</strong>
            <input
              v-else
              :ref="(el) => setRenameRef(el as HTMLInputElement | null)"
              v-model="editTitle"
              class="session-name-input"
              @blur="submitRename(s)"
              @keydown.enter.prevent="submitRename(s)"
              @keydown.escape.prevent="cancelRename"
            />
            <span v-if="s.meta">{{ s.meta }}</span>
          </span>
          <span class="conversation-actions">
            <span
              v-if="s.status"
              class="status"
              :class="statusClass(s.status)"
              :title="statusLabel(s.status)"
              :aria-label="`状态：${statusLabel(s.status)}`"
              role="img"
            ></span>
            <button
              v-if="allowSessionDelete"
              class="conversation-delete"
              type="button"
              title="删除会话"
              :aria-label="`删除会话 ${s.title || s.id.slice(0, 8)}`"
              :data-session-delete="s.id"
              @click.stop="emit('delete-session', s.id)"
            >×</button>
          </span>
        </div>
        <button
          v-if="hiddenCount(group) > 0"
          type="button"
          class="conversation-more"
          @click.stop="toggleGroupExpand(group.id)"
        >
          还有 {{ hiddenCount(group) }} 个会话
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, nextTick } from 'vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface SessionItem {
  id: string
  title: string
  createdAt?: string
  updatedAt?: string
  status?: string
  meta?: string
  metadata?: Record<string, unknown>
}

export interface ProjectGroup {
  id: string
  name: string
  workRoot?: string
  sessions: SessionItem[]
}

// ---------------------------------------------------------------------------
// Props / Emits
// ---------------------------------------------------------------------------
const props = withDefaults(
  defineProps<{
    projectGroups: ProjectGroup[]
    activeSessionId?: string
    /** Max sessions visible per project before fold (0 = no limit) */
    projectSessionLimit?: number
    /** Allow inline rename on session title click */
    allowRename?: boolean
    /** Show + button per project */
    allowProjectNewSession?: boolean
    /** Show × delete button per project */
    allowProjectDelete?: boolean
    /** Show × delete button per session */
    allowSessionDelete?: boolean
    /** Allow clicking project name to select */
    allowProjectClick?: boolean
    /** Allow right-click on project name */
    allowProjectContextMenu?: boolean
  }>(),
  {
    projectSessionLimit: 0,
    allowRename: true,
    allowProjectNewSession: true,
    allowProjectDelete: false,
    allowSessionDelete: false,
    allowProjectClick: false,
    allowProjectContextMenu: false,
  },
)

const emit = defineEmits<{
  'select-session': [id: string]
  'select-project': [id: string]
  'new-session': [projectGroupId: string]
  'delete-project': [projectGroupId: string]
  'delete-session': [sessionId: string]
  'project-context-menu': [projectGroupId: string]
  'rename-session': [sessionId: string, newTitle: string]
}>()

// ---------------------------------------------------------------------------
// Group expand/collapse
// ---------------------------------------------------------------------------
const groupExpanded = reactive<Record<string, boolean>>({})

function toggleGroupExpand(groupId: string) {
  groupExpanded[groupId] = !groupExpanded[groupId]
}

function visibleSessions(group: ProjectGroup): SessionItem[] {
  if (props.projectSessionLimit <= 0 || groupExpanded[group.id]) {
    return group.sessions
  }
  return group.sessions.slice(0, props.projectSessionLimit)
}

function sessionOrdinal(group: ProjectGroup, session: SessionItem): number {
  const ordered = [...group.sessions].sort(compareSessionCreatedAsc)
  const index = ordered.findIndex((item) => item.id === session.id)
  return index >= 0 ? index + 1 : 0
}

function compareSessionCreatedAsc(a: SessionItem, b: SessionItem): number {
  const at = sessionCreatedTime(a)
  const bt = sessionCreatedTime(b)
  if (at !== bt) return at - bt
  return a.id.localeCompare(b.id)
}

function sessionCreatedTime(session: SessionItem): number {
  const timestamp = Date.parse(session.createdAt || '')
  return Number.isFinite(timestamp) ? timestamp : Number.MAX_SAFE_INTEGER
}

function hiddenCount(group: ProjectGroup): number {
  if (props.projectSessionLimit <= 0 || groupExpanded[group.id]) return 0
  return Math.max(0, group.sessions.length - props.projectSessionLimit)
}

function isGroupActive(group: ProjectGroup): boolean {
  return group.sessions.some((s) => s.id === props.activeSessionId)
}

function statusClass(status: string): string {
  const s = status.toLowerCase()
  if (s === 'running') return 'running'
  if (s === 'completed' || s === 'done') return 'completed'
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'waiting' || s === 'pending') return 'waiting'
  if (s === 'idle' || s === 'active') return 'idle'
  return ''
}

function statusLabel(status: string): string {
  const s = status.toLowerCase()
  if (s === 'running') return '运行中'
  if (s === 'completed' || s === 'done') return '已完成'
  if (s === 'failed' || s === 'error') return '失败'
  if (s === 'waiting' || s === 'pending') return '等待中'
  if (s === 'idle' || s === 'active') return '空闲'
  return status
}

// ---------------------------------------------------------------------------
// Inline rename
// ---------------------------------------------------------------------------
const renamingId = ref<string | null>(null)
const editTitle = ref('')
const renameInputRef = ref<HTMLInputElement | null>(null)

function setRenameRef(el: HTMLInputElement | null) {
  if (el) {
    renameInputRef.value = el
    nextTick(() => el.focus())
  }
}

function startRename(session: SessionItem) {
  if (!props.allowRename) return
  renamingId.value = session.id
  editTitle.value = session.title
}

function submitRename(session: SessionItem) {
  if (renamingId.value !== session.id) return
  const title = editTitle.value.trim()
  renamingId.value = null
  if (title && title !== session.title) {
    emit('rename-session', session.id, title)
  }
}

function cancelRename() {
  renamingId.value = null
  editTitle.value = ''
}
</script>

<style scoped>
.conversation-more {
  width: 100%;
  padding: 6px 8px;
  border-radius: 8px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-backdrop-text) 64%, transparent);
  font-size: 12px;
  text-align: center;
}
.conversation-more:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text) 7%, transparent);
  color: var(--theme-backdrop-text);
}
.session-name-input {
  width: 100%;
  min-width: 0;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 30%, var(--blue));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-backdrop-text) 8%, transparent);
  color: var(--theme-backdrop-text);
  padding: 2px 6px;
  font-size: 13px;
  outline: none;
}
</style>
