<template>
  <div class="session-sidebar-content">
    <div v-if="projectGroups.length === 0" class="sidebar-empty">
      <slot name="empty">暂无内容，创建一个开始。</slot>
    </div>

    <section
      v-for="section in projectSections"
      :key="section.id"
      class="sidebar-section"
      :data-sidebar-section="section.id"
    >
      <h2 v-if="section.label" class="sidebar-section-title">{{ section.label }}</h2>
      <article
        v-for="group in section.groups"
        :key="group.id"
        class="project-block"
        :class="{ active: isGroupActive(group) }"
        :data-collapsed="isCollapsed(group.id) || undefined"
      >
      <div class="project-top">
        <div class="project-btns">
          <button
            class="project-action project-fold"
            type="button"
            :title="isCollapsed(group.id) ? '展开会话' : '收起会话'"
            :aria-label="isCollapsed(group.id) ? `展开 ${group.name} 会话` : `收起 ${group.name} 会话`"
            :aria-expanded="!isCollapsed(group.id)"
            :data-project-fold="group.id"
            @click.stop="toggleProjectCollapse(group.id)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
          </button>
          <button
            class="project-action menu-trigger"
            type="button"
            title="项目操作"
            :aria-label="`${group.name} 项目操作`"
            :aria-expanded="openProjectMenuId === group.id"
            :data-project-menu-trigger="group.id"
            @click.stop="toggleProjectMenu(group.id)"
          ><MoreHorizontal :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
        </div>
        <button
          type="button"
          class="project-name"
          :class="{ clickable: allowProjectClick && group.canManage !== false }"
          :data-project-entry="group.id"
          :disabled="group.canManage === false"
          @click="selectProject(group.id, group.canManage !== false)"
          @keydown.enter.prevent="selectProject(group.id, group.canManage !== false)"
          @keydown.space.prevent="selectProject(group.id, group.canManage !== false)"
          @contextmenu.prevent="allowProjectContextMenu && group.canManage !== false && emit('project-context-menu', group.id)"
        >
          <strong>{{ group.name }}</strong>
          <span v-if="group.workRoot" class="work-root">{{ group.workRoot }}</span>
          <span v-else class="work-root">{{ group.sessions.length }} 个会话</span>
        </button>
      </div>

      <div class="conversation-list" v-show="!isCollapsed(group.id)">
        <div
          v-for="s in visibleSessions(group)"
          :key="s.id"
          v-motion-enter="!initialSessionIds.has(s.id)"
          class="conversation"
          :class="{ active: s.id === activeSessionId }"
          :data-session-row="s.id"
        >
          <button
            class="conversation-select"
            type="button"
            :data-session-select="s.id"
            :aria-label="`打开会话 ${s.title || s.id.slice(0, 8)}`"
            @click="emit('select-session', s.id)"
          >
            <span class="conversation-main">
              <strong>{{ s.title || `Session ${s.id.slice(0, 8)}` }}</strong>
              <span v-if="s.meta">{{ s.meta }}</span>
            </span>
          </button>
          <span class="conversation-actions">
            <span
              v-if="s.status"
              class="status conversation-status"
              :class="statusClass(s.status)"
              :title="statusLabel(s.status)"
              :aria-label="`状态：${statusLabel(s.status)}`"
              role="img"
            ></span>
            <span class="conversation-hover-actions">
              <button
                class="conversation-action pin"
                :class="{ active: isSessionPinned(s.id) }"
                type="button"
                :title="isSessionPinned(s.id) ? '取消置顶' : '置顶会话'"
                :aria-label="`${isSessionPinned(s.id) ? '取消置顶' : '置顶'}会话 ${s.title || s.id.slice(0, 8)}`"
                :aria-pressed="isSessionPinned(s.id)"
                :data-session-pin="s.id"
                @click="toggleSessionPin(s.id)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 4 6 6-3 1-3 4 1 3-1 1-4-4-5 5-1-1 5-5-4-4 1-1 3 1 4-3 1-3Z" /></svg>
              </button>
              <button
                v-if="allowSessionDelete"
                class="conversation-action delete"
                type="button"
                title="删除会话"
                :aria-label="`删除会话 ${s.title || s.id.slice(0, 8)}`"
                :data-session-delete="s.id"
                @click="emit('delete-session', s.id)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3m2 0-1 13H8L7 7m3 4v5m4-5v5" /></svg>
              </button>
            </span>
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
      <div
        v-if="openProjectMenuId === group.id"
        class="project-menu"
        role="menu"
        :aria-label="`${group.name} 项目操作`"
        :data-project-menu="group.id"
        @pointerdown.stop
        @click.stop
        @keydown.escape.prevent="closeProjectMenu"
      >
        <button
          v-if="allowProjectNewSession && group.canManage !== false"
          role="menuitem"
          :disabled="isProjectBusy(group.id)"
          :data-project-new="group.id"
          @click="runProjectAction(group.id, 'new-session')"
        >{{ isProjectBusy(group.id) ? '正在创建…' : newSessionLabel }}</button>
        <button role="menuitem" :data-project-pin="group.id" @click="runProjectAction(group.id, 'pin')">
          {{ isPinned(group.id) ? '取消置顶' : '置顶项目' }}
        </button>
        <button
          v-if="group.sessions.length > projectSessionLimit && projectSessionLimit > 0"
          role="menuitem"
          @click="runProjectAction(group.id, 'fold')"
        >{{ groupExpanded[group.id] ? '收起会话' : '展开全部会话' }}</button>
        <button
          v-if="allowProjectContextMenu && group.canManage !== false"
          role="menuitem"
          @click="runProjectAction(group.id, 'settings')"
        >项目设置</button>
        <span v-if="allowProjectDelete && group.canManage !== false" class="project-menu-separator"></span>
        <button
          v-if="allowProjectDelete && group.canManage !== false"
          class="danger"
          role="menuitem"
          @click="runProjectAction(group.id, 'delete')"
        >删除项目</button>
      </div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onBeforeUnmount, onMounted } from 'vue'
import { MoreHorizontal } from 'lucide-vue-next'
import { motionEnterDirective } from '../directives/motionEnter'

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
  canManage?: boolean
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
    /** Show + button per project */
    allowProjectNewSession?: boolean
    /** Label for the per-project new-session button (e.g. '新建工作流' in workflow mode). */
    newSessionLabel?: string
    /** Show × delete button per project */
    allowProjectDelete?: boolean
    /** Show × delete button per session */
    allowSessionDelete?: boolean
    /** Allow clicking project name to select */
    allowProjectClick?: boolean
    /** Allow right-click on project name */
    allowProjectContextMenu?: boolean
    /** Project ids with an in-flight new-session request. */
    busyProjectIds?: readonly string[]
    /** localStorage key used to persist pinned projects. Empty disables persistence. */
    pinStorageKey?: string
  }>(),
  {
    projectSessionLimit: 0,
    allowProjectNewSession: true,
    newSessionLabel: '新建会话',
    allowProjectDelete: false,
    allowSessionDelete: false,
    allowProjectClick: false,
    allowProjectContextMenu: false,
    busyProjectIds: () => [],
    pinStorageKey: '',
  },
)

const emit = defineEmits<{
  'select-session': [id: string]
  'select-project': [id: string]
  'new-session': [projectGroupId: string]
  'delete-project': [projectGroupId: string]
  'delete-session': [sessionId: string]
  'project-context-menu': [projectGroupId: string]
}>()

// ---------------------------------------------------------------------------
// Group expand/collapse
// ---------------------------------------------------------------------------
const groupExpanded = reactive<Record<string, boolean>>({})
const groupCollapsed = reactive<Record<string, boolean>>(loadCollapsedProjectIds())
const pinnedProjectIds = ref<string[]>(loadPinnedProjectIds())
const pinnedSessionIds = ref<string[]>(loadPinnedSessionIds())
const openProjectMenuId = ref<string | null>(null)

// ── 新会话条目入场（C14）：挂载时已在列表中的会话不播，之后新出现的会话淡入。
//    集合 setup 期捕获、只读，不引入响应式状态（会话列表变更频率极低）。
const initialSessionIds = new Set(props.projectGroups.flatMap((g) => g.sessions.map((s) => s.id)))
const vMotionEnter = motionEnterDirective

const projectSections = computed(() => {
  const pinned = props.projectGroups.filter((group) => isPinned(group.id))
  const others = props.projectGroups.filter((group) => !isPinned(group.id))
  return [
    { id: 'pinned', label: 'PINNED', groups: pinned },
    { id: 'default', label: '', groups: others },
  ].filter((section) => section.groups.length > 0)
})

function loadPinnedProjectIds(): string[] {
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return []
  try {
    const stored = JSON.parse(localStorage.getItem(props.pinStorageKey) || '[]')
    return Array.isArray(stored) ? stored.filter((id): id is string => typeof id === 'string') : []
  } catch {
    return []
  }
}

function isPinned(groupId: string): boolean {
  return pinnedProjectIds.value.includes(groupId)
}

function toggleProjectPin(groupId: string) {
  pinnedProjectIds.value = isPinned(groupId)
    ? pinnedProjectIds.value.filter((id) => id !== groupId)
    : [...pinnedProjectIds.value, groupId]
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(props.pinStorageKey, JSON.stringify(pinnedProjectIds.value))
  } catch {
    // Pinning still works for this session when browser storage is unavailable.
  }
}

function loadCollapsedProjectIds(): Record<string, boolean> {
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return {}
  try {
    const stored = JSON.parse(localStorage.getItem(`${props.pinStorageKey}.collapsed`) || '[]')
    if (!Array.isArray(stored)) return {}
    const map: Record<string, boolean> = {}
    for (const id of stored) {
      if (typeof id === 'string') map[id] = true
    }
    return map
  } catch {
    return {}
  }
}

function isCollapsed(groupId: string): boolean {
  return !!groupCollapsed[groupId]
}

function toggleProjectCollapse(groupId: string) {
  if (groupCollapsed[groupId]) {
    delete groupCollapsed[groupId]
  } else {
    groupCollapsed[groupId] = true
  }
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return
  try {
    const ids = Object.keys(groupCollapsed)
    localStorage.setItem(`${props.pinStorageKey}.collapsed`, JSON.stringify(ids))
  } catch {
    // Collapse still works for this session when browser storage is unavailable.
  }
}

function loadPinnedSessionIds(): string[] {
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return []
  try {
    const stored = JSON.parse(localStorage.getItem(`${props.pinStorageKey}.sessions`) || '[]')
    return Array.isArray(stored) ? stored.filter((id): id is string => typeof id === 'string') : []
  } catch {
    return []
  }
}

function isSessionPinned(sessionId: string): boolean {
  return pinnedSessionIds.value.includes(sessionId)
}

function toggleSessionPin(sessionId: string) {
  pinnedSessionIds.value = isSessionPinned(sessionId)
    ? pinnedSessionIds.value.filter((id) => id !== sessionId)
    : [...pinnedSessionIds.value, sessionId]
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(`${props.pinStorageKey}.sessions`, JSON.stringify(pinnedSessionIds.value))
  } catch {
    // Session pinning remains available until reload.
  }
}

function toggleProjectMenu(groupId: string) {
  openProjectMenuId.value = openProjectMenuId.value === groupId ? null : groupId
}

function closeProjectMenu() {
  openProjectMenuId.value = null
}

function handleDocumentPointerDown() {
  closeProjectMenu()
}

function handleDocumentKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeProjectMenu()
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeyDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeyDown)
})

function runProjectAction(groupId: string, action: 'new-session' | 'pin' | 'fold' | 'settings' | 'delete') {
  closeProjectMenu()
  if (action === 'new-session') emit('new-session', groupId)
  if (action === 'pin') toggleProjectPin(groupId)
  if (action === 'fold') toggleGroupExpand(groupId)
  if (action === 'settings') emit('project-context-menu', groupId)
  if (action === 'delete') emit('delete-project', groupId)
}

function toggleGroupExpand(groupId: string) {
  groupExpanded[groupId] = !groupExpanded[groupId]
}

function isProjectBusy(projectId: string): boolean {
  return props.busyProjectIds.includes(projectId)
}

function selectProject(projectId: string, canManage: boolean) {
  if (props.allowProjectClick && canManage) emit('select-project', projectId)
}

function visibleSessions(group: ProjectGroup): SessionItem[] {
  const ordered = [...group.sessions].sort((a, b) => {
    const pa = isSessionPinned(a.id) ? 1 : 0
    const pb = isSessionPinned(b.id) ? 1 : 0
    if (pa !== pb) return pb - pa
    return sessionActivityTime(b) - sessionActivityTime(a)
  })
  if (props.projectSessionLimit <= 0 || groupExpanded[group.id]) return ordered
  return ordered.slice(0, props.projectSessionLimit)
}

function sessionActivityTime(session: SessionItem): number {
  const updated = Date.parse(session.updatedAt || '')
  const created = Date.parse(session.createdAt || '')
  if (Number.isFinite(updated)) return updated
  if (Number.isFinite(created)) return created
  return 0
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

</script>

<style scoped>
.conversation-more {
  width: 100%;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-backdrop-text) 64%, transparent);
  font-size: 12px;
  text-align: center;
}
.conversation-more:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text) 7%, transparent);
  color: var(--theme-backdrop-text);
}
.project-name {
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  font: inherit;
  text-align: left;
}
</style>
