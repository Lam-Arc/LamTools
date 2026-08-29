<template>
  <div class="session-sidebar-content">
    <span ref="dragImageRef" class="sidebar-drag-image" aria-hidden="true"></span>
    <div v-if="hasProjectData" class="sidebar-toolbar">
      <div
        class="sidebar-search-wrap"
        :class="{ 'is-expanded': searchExpanded || Boolean(normalizedQuery) }"
      >
        <button
          class="sidebar-search-toggle"
          type="button"
          aria-label="搜索项目和会话"
          :aria-expanded="searchExpanded || Boolean(normalizedQuery)"
          data-sidebar-search-toggle
          @click="focusSearchInput"
          @focus="searchExpanded = true"
        >
          <Search :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <input
          ref="searchInputRef"
          v-model="searchQuery"
          class="sidebar-search"
          type="search"
          placeholder="搜索项目和会话"
          aria-label="搜索项目和会话"
          data-sidebar-search
          @focus="searchExpanded = true"
          @blur="collapseSearchIfEmpty"
        />
      </div>

    </div>
    <div v-if="!hasProjectData" class="sidebar-empty">
      <slot name="empty">暂无内容，创建一个开始。</slot>
    </div>
    <div
      v-else-if="normalizedQuery && filteredGroups.length === 0"
      class="sidebar-empty sidebar-search-empty"
      data-sidebar-search-empty
    >
      <p>未找到匹配的项目或会话</p>
      <button
        type="button"
        class="sidebar-search-clear"
        data-sidebar-search-clear
        @click="searchQuery = ''"
      >
        清除搜索
      </button>
    </div>

    <section
      v-for="section in projectSections"
      :key="section.id"
      class="sidebar-section"
      :data-sidebar-section="section.id"
    >
      <h2 v-if="section.label" class="sidebar-section-title">{{ section.label }}</h2>
      <TransitionGroup name="sidebar-sort" tag="div" class="sidebar-project-groups">
        <article
          v-for="group in section.groups"
          :key="group.id"
          class="project-block"
          :class="{ active: isGroupActive(group) }"
          :data-collapsed="isCollapsed(group.id) || undefined"
        >
      <div
        class="project-row"
        :class="{
          'is-dragging': isDragging('project', group.id, undefined, section.id),
        }"
        :draggable="!normalizedQuery"
        :data-project-row="group.id"
        @dragstart="startProjectDrag(group.id, section.id, $event)"
        @dragover.prevent="handleProjectDragOver(group.id, section.id, $event)"
        @drop.prevent="dropProject(group.id, section.id)"
        @dragend="finishDrag"
      >
        <button
          class="project-action project-fold project-toggle"
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
          type="button"
          class="project-name project-main"
          :class="{ clickable: allowProjectClick && group.canManage !== false }"
          :data-project-entry="group.id"
          :disabled="group.canManage === false"
          @click="selectProject(group.id, group.canManage !== false)"
          @keydown.enter.prevent="selectProject(group.id, group.canManage !== false)"
          @keydown.space.prevent="selectProject(group.id, group.canManage !== false)"
          @contextmenu.prevent="allowProjectContextMenu && group.canManage !== false && emit('project-context-menu', group.id)"
        >
          <strong>{{ group.name }}</strong>
        </button>
        <div class="project-btns">
          <button
            class="project-action menu-trigger project-menu-button"
            type="button"
            title="项目操作"
            :aria-label="`${group.name} 项目操作`"
            :aria-expanded="openProjectMenuKey === projectMenuKey(section.id, group.id)"
            :data-project-menu-trigger="group.id"
            @click.stop="toggleProjectMenu(section.id, group.id)"
          ><MoreHorizontal :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
        </div>
      </div>

      <div class="conversation-list" v-show="!isCollapsed(group.id)">
        <div
          v-if="group.sessions.length === 0"
          class="sidebar-project-empty"
          data-project-empty
        >
          <span>暂无会话</span>
          <button
            v-if="allowProjectNewSession && group.canManage !== false"
            class="sidebar-project-empty-action"
            type="button"
            :disabled="isProjectBusy(group.id)"
            :data-project-empty-new="group.id"
            @click.stop="emit('new-session', group.id)"
          >
            {{ isProjectBusy(group.id) ? '正在创建…' : `＋ ${newSessionLabel}` }}
          </button>
        </div>
        <TransitionGroup name="sidebar-sort" tag="div" class="conversation-items">
          <div
            v-for="s in visibleSessions(group, section.id)"
            :key="s.id"
            v-motion-enter="!initialSessionIds.has(s.id)"
            class="conversation session-row"
            :class="{
              active: s.id === activeSessionId,
              'is-active': s.id === activeSessionId,
              'is-dragging': isDragging('session', s.id, group.id, section.id),
            }"
            :draggable="!normalizedQuery"
            :data-session-row="s.id"
            @dragstart="startSessionDrag(group.id, s.id, section.id, $event)"
            @dragover.prevent="handleSessionDragOver(group.id, s.id, section.id, $event)"
            @drop.prevent="dropSession(group.id, s.id, section.id)"
            @dragend="finishDrag"
            @contextmenu.prevent.stop="handleSessionContextMenu(s.id, $event)"
          >
          <button
            v-if="editingSessionId !== s.id"
            class="conversation-select session-main"
            type="button"
            :data-session-select="s.id"
            :aria-label="`打开会话 ${s.title || s.id.slice(0, 8)}`"
            @click="selectSession(s.id)"
          >
            <span class="conversation-main">
              <strong class="session-title">{{ s.title || `Session ${s.id.slice(0, 8)}` }}</strong>
              <span v-if="s.meta">{{ s.meta }}</span>
            </span>
          </button>
          <div v-else class="conversation-select session-main session-editing" @click.stop>
            <span class="conversation-main">
              <input
                v-model="sessionNameDraft"
                class="session-name-input"
                type="text"
                :data-session-name-input="s.id"
                :aria-label="`重命名会话 ${s.title || s.id.slice(0, 8)}`"
                autocomplete="off"
                spellcheck="false"
                @click.stop
                @keydown.enter.prevent.stop="commitSessionRename(s.id)"
                @keydown.esc.prevent.stop="cancelSessionRename"
              />
              <span v-if="s.meta">{{ s.meta }}</span>
            </span>
          </div>
          <span class="conversation-actions">
            <span
              v-if="shouldShowStatus(s)"
              class="status conversation-status session-status"
              :class="statusClass(s.status || '')"
              :title="statusLabel(s.status || '')"
              :aria-label="`状态：${statusLabel(s.status || '')}`"
              role="img"
            ></span>
          </span>
          </div>
        </TransitionGroup>
        <button
          v-if="hiddenCount(group, section.id) > 0"
          type="button"
          class="conversation-more"
          @click.stop="toggleGroupExpand(group.id)"
        >
          还有 {{ hiddenCount(group, section.id) }} 个会话
        </button>
        </div>
        <div
          v-if="openProjectMenuKey === projectMenuKey(section.id, group.id)"
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
      </TransitionGroup>
    </section>

    <Teleport to="body">
      <div
        v-if="openSessionMenuState"
        ref="sessionMenuRef"
        class="session-context-menu"
        role="menu"
        :aria-label="`${sessionMenuTitle} 会话操作`"
        :data-session-menu="openSessionId"
        :data-placement="sessionMenuPlacement"
        :style="sessionMenuPosition"
        @pointerdown.stop
        @click.stop
        @keydown.escape.prevent="closeSessionMenus"
      >
        <button
          type="button"
          role="menuitem"
          :aria-pressed="isSessionPinned(openSessionId)"
          :data-session-menu-pin="openSessionId"
          @click="runSessionAction('pin', openSessionId)"
        >{{ isSessionPinned(openSessionId) ? '取消置顶' : '置顶会话' }}</button>
        <button
          type="button"
          role="menuitem"
          :data-session-menu-rename="openSessionId"
          @click="runSessionAction('rename', openSessionId)"
        >重命名</button>
        <button
          ref="sessionExportTriggerRef"
          type="button"
          role="menuitem"
          aria-haspopup="menu"
          :aria-expanded="sessionExportMenuOpen"
          :data-session-menu-export="openSessionId"
          @click="runSessionAction('export', openSessionId)"
        >
          <span>导出</span>
          <ChevronRight class="session-menu-chevron" :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <span v-if="allowSessionDelete" class="session-menu-separator" aria-hidden="true"></span>
        <button
          v-if="allowSessionDelete"
          class="danger"
          type="button"
          role="menuitem"
          :data-session-menu-delete="openSessionId"
          @click="runSessionAction('delete', openSessionId)"
        >删除</button>
      </div>

      <div
        v-if="openSessionMenuState && sessionExportMenuOpen"
        ref="sessionExportMenuRef"
        class="session-export-menu"
        role="menu"
        aria-label="导出"
        :data-session-export-menu="openSessionId"
        :data-placement="sessionExportPlacement"
        :style="sessionExportMenuPosition"
        @pointerdown.stop
        @click.stop
        @keydown.escape.prevent="closeSessionMenus"
      >
        <div class="session-export-group-label" role="presentation">文本记录</div>
        <button type="button" role="menuitem" data-session-export-format="markdown" @click="exportSession(openSessionId, 'markdown')">Markdown</button>
        <button type="button" role="menuitem" data-session-export-format="txt" @click="exportSession(openSessionId, 'txt')">TXT</button>
        <button type="button" role="menuitem" data-session-export-format="jsonl" @click="exportSession(openSessionId, 'jsonl')">JSONL</button>
        <button type="button" role="menuitem" data-session-export-format="handoff" :data-session-export-handoff="openSessionId" @click="exportSession(openSessionId, 'handoff')">Agent Handoff</button>
        <span class="session-menu-separator" aria-hidden="true"></span>
        <button type="button" role="menuitem" data-session-export-format="zip" :data-session-export-full="openSessionId" @click="exportSession(openSessionId, 'zip')">完整归档</button>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, reactive, onBeforeUnmount, onMounted, watch } from 'vue'
import { ChevronRight, MoreHorizontal, Search } from 'lucide-vue-next'
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

type DragPosition = 'before' | 'after'

type DragState =
  | { kind: 'project'; id: string; sectionId: string }
  | { kind: 'session'; id: string; groupId: string; sectionId: string }

interface DragOverTarget {
  kind: DragState['kind']
  id: string
  groupId?: string
  sectionId: string
  position: DragPosition
}

// ---------------------------------------------------------------------------
// Props / Emits
// ---------------------------------------------------------------------------
const props = withDefaults(
  defineProps<{
    projectGroups: ProjectGroup[]
    /** Whether real projects exist; separate from compatibility groups. */
    hasProjects?: boolean
    activeSessionId?: string
    /** Max sessions visible per project before fold (0 = no limit) */
    projectSessionLimit?: number
    /** Show + button per project */
    allowProjectNewSession?: boolean
    /** Label for the per-project new-session button. */
    newSessionLabel?: string
    /** Show × delete button per project */
    allowProjectDelete?: boolean
    /** Show × delete button per session */
    allowSessionDelete?: boolean
    /** Allow right-click session actions (rename/export/pin/delete). */
    allowSessionContextMenu?: boolean
    /** Allow clicking project name to select */
    allowProjectClick?: boolean
    /** Allow right-click on project name */
    allowProjectContextMenu?: boolean
    /** Project ids with an in-flight new-session request. */
    busyProjectIds?: readonly string[]
    /** localStorage key used to persist pins, collapse state, and manual order. Empty disables persistence. */
    pinStorageKey?: string
  }>(),
  {
    hasProjects: undefined,
    projectSessionLimit: 0,
    allowProjectNewSession: true,
    newSessionLabel: '新建会话',
    allowProjectDelete: false,
    allowSessionDelete: false,
    allowSessionContextMenu: true,
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
  'rename-session': [sessionId: string, title: string]
  'export-session': [sessionId: string, format: SessionExportFormat]
  'project-context-menu': [projectGroupId: string]
}>()

export type SessionExportFormat = 'markdown' | 'txt' | 'jsonl' | 'handoff' | 'zip'

// ---------------------------------------------------------------------------
// Group expand/collapse
// ---------------------------------------------------------------------------
const groupExpanded = reactive<Record<string, boolean>>({})
const groupCollapsed = reactive<Record<string, boolean>>(loadCollapsedProjectIds())
const pinnedProjectIds = ref<string[]>(loadPinnedProjectIds())
const pinnedSessionIds = ref<string[]>(loadPinnedSessionIds())
const projectOrderIds = ref<string[]>(loadOrderIds('order.projects'))
const sessionOrderIds = ref<Record<string, string[]>>(loadSessionOrderIds())
const dragState = ref<DragState | null>(null)
const dragOverTarget = ref<DragOverTarget | null>(null)
const openProjectMenuKey = ref<string | null>(null)
type SessionMenuAction = 'pin' | 'rename' | 'export' | 'delete'
interface SessionMenuState {
  sessionId: string
  clientX: number
  clientY: number
}
type FixedMenuPosition = { left: string; top: string }

const openSessionMenuState = ref<SessionMenuState | null>(null)
const sessionMenuPosition = ref<FixedMenuPosition>({ left: '0px', top: '0px' })
const sessionExportMenuPosition = ref<FixedMenuPosition>({ left: '0px', top: '0px' })
const sessionMenuPlacement = ref<'down' | 'up'>('down')
const sessionExportPlacement = ref<'right' | 'left'>('right')
const sessionExportMenuOpen = ref(false)
const sessionMenuRef = ref<HTMLElement | null>(null)
const sessionExportTriggerRef = ref<HTMLButtonElement | null>(null)
const sessionExportMenuRef = ref<HTMLElement | null>(null)
const editingSessionId = ref<string | null>(null)
const sessionNameDraft = ref('')
const searchQuery = ref('')
const searchExpanded = ref(false)
const searchInputRef = ref<HTMLInputElement | null>(null)
const dragImageRef = ref<HTMLElement | null>(null)
const normalizedQuery = computed(() => searchQuery.value.trim().toLocaleLowerCase())
const hasProjectData = computed(() => props.hasProjects ?? props.projectGroups.length > 0)
const openSessionId = computed(() => openSessionMenuState.value?.sessionId || '')
const sessionMenuTitle = computed(() => {
  const session = findSession(openSessionId.value)
  return session?.title || (openSessionId.value ? `Session ${openSessionId.value.slice(0, 8)}` : '会话')
})

// ── 新会话条目入场（C14）：挂载时已在列表中的会话不播，之后新出现的会话淡入。
//    集合 setup 期捕获、只读，不引入响应式状态（会话列表变更频率极低）。
const initialSessionIds = new Set(props.projectGroups.flatMap((g) => g.sessions.map((s) => s.id)))
const vMotionEnter = motionEnterDirective

const filteredGroups = computed(() => {
  if (!hasProjectData.value) return []

  const query = normalizedQuery.value
  if (!query) return props.projectGroups

  return props.projectGroups.flatMap((group) => {
    const projectMatches = group.name.toLocaleLowerCase().includes(query)
    const sessions = projectMatches
      ? group.sessions
      : group.sessions.filter((session) => (session.title || '').toLocaleLowerCase().includes(query))
    if (!projectMatches && sessions.length === 0) return []
    return [{ ...group, sessions }]
  })
})

const orderedGroups = computed(() => {
  const groups = filteredGroups.value
  const groupsById = new Map(groups.map((group) => [group.id, group]))
  return normalizeOrder(groups.map((group) => group.id), previewProjectOrderIds())
    .flatMap((id) => {
      const group = groupsById.get(id)
      return group ? [group] : []
    })
})

const projectSections = computed(() => {
  if (!hasProjectData.value) return []

  const pinned = orderedGroups.value.flatMap((group) => {
    if (isPinned(group.id)) return [group]
    const sessions = orderedSessions(group, 'pinned').filter((session) => isSessionPinned(session.id))
    return sessions.length > 0 ? [{ ...group, sessions }] : []
  })
  const others = orderedGroups.value.filter((group) => !isPinned(group.id))
  return [
    { id: 'pinned', label: 'PINNED', groups: pinned },
    { id: 'default', label: '项目', groups: others },
  ].filter((section) => section.groups.length > 0)
})

function focusSearchInput() {
  searchExpanded.value = true
  void nextTick(() => searchInputRef.value?.focus())
}

function collapseSearchIfEmpty() {
  if (!normalizedQuery.value) searchExpanded.value = false
}

function loadPinnedProjectIds(): string[] {
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return []
  try {
    const stored = JSON.parse(localStorage.getItem(props.pinStorageKey) || '[]')
    return Array.isArray(stored) ? stored.filter((id): id is string => typeof id === 'string') : []
  } catch {
    return []
  }
}

function readSidebarStorage(suffix: string): unknown {
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return null
  try {
    return JSON.parse(localStorage.getItem(`${props.pinStorageKey}.${suffix}`) || 'null')
  } catch {
    return null
  }
}

function loadOrderIds(suffix: string): string[] {
  const stored = readSidebarStorage(suffix)
  return Array.isArray(stored)
    ? stored.filter((id): id is string => typeof id === 'string')
    : []
}

function loadSessionOrderIds(): Record<string, string[]> {
  const stored = readSidebarStorage('order.sessions')
  if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return {}

  const result: Record<string, string[]> = {}
  for (const [groupId, ids] of Object.entries(stored)) {
    if (Array.isArray(ids)) {
      result[groupId] = ids.filter((id): id is string => typeof id === 'string')
    }
  }
  return result
}

function persistSidebarOrder(suffix: string, value: unknown): void {
  if (!props.pinStorageKey || typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(`${props.pinStorageKey}.${suffix}`, JSON.stringify(value))
  } catch {
    // Manual order remains available until reload when browser storage fails.
  }
}

function normalizeOrder(ids: string[], preferred: readonly string[]): string[] {
  const available = new Set(ids)
  const seen = new Set<string>()
  const result: string[] = []

  for (const id of preferred) {
    if (available.has(id) && !seen.has(id)) {
      seen.add(id)
      result.push(id)
    }
  }
  for (const id of ids) {
    if (!seen.has(id)) {
      seen.add(id)
      result.push(id)
    }
  }
  return result
}

function moveId(ids: readonly string[], sourceId: string, targetId: string, position: DragPosition): string[] {
  const sourceIndex = ids.indexOf(sourceId)
  const targetIndex = ids.indexOf(targetId)
  if (sourceIndex < 0 || targetIndex < 0 || sourceId === targetId) return [...ids]

  const next = [...ids]
  next.splice(sourceIndex, 1)
  const nextTargetIndex = next.indexOf(targetId)
  next.splice(nextTargetIndex + (position === 'after' ? 1 : 0), 0, sourceId)
  return next
}

function previewProjectOrderIds(): string[] {
  const current = normalizeOrder(props.projectGroups.map((group) => group.id), projectOrderIds.value)
  const state = dragState.value
  const target = dragOverTarget.value
  if (
    !state
    || state.kind !== 'project'
    || !target
    || target.kind !== 'project'
    || target.sectionId !== state.sectionId
  ) return current
  return moveId(current, state.id, target.id, target.position)
}

function dropPosition(event: DragEvent): DragPosition {
  const element = event.currentTarget as HTMLElement | null
  if (!element) return 'before'
  const rect = element.getBoundingClientRect()
  return event.clientY >= rect.top + rect.height / 2 ? 'after' : 'before'
}

function sameOrder(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((id, index) => id === right[index])
}

function syncOrderWithProps(groups: ProjectGroup[]): void {
  const nextProjects = normalizeOrder(groups.map((group) => group.id), projectOrderIds.value)
  if (!sameOrder(nextProjects, projectOrderIds.value)) projectOrderIds.value = nextProjects

  const nextSessions = { ...sessionOrderIds.value }
  let changed = false
  for (const group of groups) {
    const current = sessionOrderIds.value[group.id] || []
    const next = normalizeOrder(group.sessions.map((session) => session.id), current)
    if (!sameOrder(next, current)) {
      nextSessions[group.id] = next
      changed = true
    }
  }
  if (changed) sessionOrderIds.value = nextSessions
}

watch(() => props.projectGroups, syncOrderWithProps, { immediate: true })

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
  if (normalizedQuery.value) return false
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

function findSession(sessionId: string): SessionItem | undefined {
  for (const group of props.projectGroups) {
    const session = group.sessions.find((item) => item.id === sessionId)
    if (session) return session
  }
  return undefined
}

function selectSession(sessionId: string): void {
  closeSessionMenus()
  cancelSessionRename()
  emit('select-session', sessionId)
}

function handleSessionContextMenu(sessionId: string, event: MouseEvent): void {
  if (!props.allowSessionContextMenu) return
  closeProjectMenu()
  cancelSessionRename()
  openSessionMenuState.value = {
    sessionId,
    clientX: event.clientX,
    clientY: event.clientY,
  }
  sessionExportMenuOpen.value = false
  sessionMenuPosition.value = {
    left: `${event.clientX}px`,
    top: `${event.clientY}px`,
  }
  void nextTick(positionSessionMenu)
}

function closeSessionMenus(): void {
  openSessionMenuState.value = null
  sessionExportMenuOpen.value = false
}

function viewportSize(): { width: number; height: number } {
  return {
    width: Math.max(window.innerWidth || 0, document.documentElement?.clientWidth || 0),
    height: Math.max(window.innerHeight || 0, document.documentElement?.clientHeight || 0),
  }
}

function clampMenuPosition(value: number, size: number, viewport: number, margin: number): number {
  const maximum = Math.max(margin, viewport - size - margin)
  return Math.min(Math.max(value, margin), maximum)
}

function positionSessionMenu(): void {
  const state = openSessionMenuState.value
  const menu = sessionMenuRef.value
  if (!state || !menu) return

  const { width: viewportWidth, height: viewportHeight } = viewportSize()
  if (viewportWidth <= 0 || viewportHeight <= 0) return

  const rect = menu.getBoundingClientRect()
  const width = rect.width || 192
  const height = rect.height || (props.allowSessionDelete ? 184 : 144)
  const margin = 8
  let left = state.clientX
  let top = state.clientY
  sessionMenuPlacement.value = 'down'

  if (left + width + margin > viewportWidth) {
    left = state.clientX - width
  }
  if (top + height + margin > viewportHeight) {
    top = state.clientY - height
    sessionMenuPlacement.value = 'up'
  }

  sessionMenuPosition.value = {
    left: `${Math.round(clampMenuPosition(left, width, viewportWidth, margin))}px`,
    top: `${Math.round(clampMenuPosition(top, height, viewportHeight, margin))}px`,
  }
  if (sessionExportMenuOpen.value) void nextTick(positionSessionExportMenu)
}

function toggleSessionExportMenu(): void {
  sessionExportMenuOpen.value = !sessionExportMenuOpen.value
  if (sessionExportMenuOpen.value) void nextTick(positionSessionExportMenu)
}

function positionSessionExportMenu(): void {
  const menu = sessionExportMenuRef.value
  const trigger = sessionExportTriggerRef.value
  if (!menu || !trigger) return

  const { width: viewportWidth, height: viewportHeight } = viewportSize()
  if (viewportWidth <= 0 || viewportHeight <= 0) return

  const triggerRect = trigger.getBoundingClientRect()
  const menuRect = menu.getBoundingClientRect()
  const width = menuRect.width || 176
  const height = menuRect.height || 232
  const margin = 8
  const gap = 4
  let left = triggerRect.right + gap
  let top = triggerRect.top
  sessionExportPlacement.value = 'right'

  if (left + width + margin > viewportWidth) {
    left = triggerRect.left - width - gap
    sessionExportPlacement.value = 'left'
  }
  if (top + height + margin > viewportHeight) {
    top = triggerRect.bottom - height
  }

  sessionExportMenuPosition.value = {
    left: `${Math.round(clampMenuPosition(left, width, viewportWidth, margin))}px`,
    top: `${Math.round(clampMenuPosition(top, height, viewportHeight, margin))}px`,
  }
}

function runSessionAction(action: SessionMenuAction, sessionId: string): void {
  if (!sessionId) return
  if (action === 'pin') {
    closeSessionMenus()
    toggleSessionPin(sessionId)
    return
  }
  if (action === 'rename') {
    startSessionRename(sessionId)
    return
  }
  if (action === 'export') {
    toggleSessionExportMenu()
    return
  }
  closeSessionMenus()
  emit('delete-session', sessionId)
}

function exportSession(sessionId: string, format: SessionExportFormat): void {
  closeSessionMenus()
  emit('export-session', sessionId, format)
}

function startSessionRename(sessionId: string): void {
  const session = findSession(sessionId)
  if (!session) return
  closeSessionMenus()
  editingSessionId.value = sessionId
  sessionNameDraft.value = session.title || `Session ${sessionId.slice(0, 8)}`
  void nextTick(() => {
    const input = document.querySelector<HTMLInputElement>('[data-session-name-input]')
    input?.focus()
    input?.select()
  })
}

function cancelSessionRename(): void {
  editingSessionId.value = null
  sessionNameDraft.value = ''
}

function commitSessionRename(sessionId: string): void {
  const session = findSession(sessionId)
  const title = sessionNameDraft.value.trim()
  if (!session || !title || title === (session.title || `Session ${sessionId.slice(0, 8)}`)) {
    cancelSessionRename()
    return
  }
  cancelSessionRename()
  emit('rename-session', sessionId, title)
}

function projectMenuKey(sectionId: string, groupId: string): string {
  return `${sectionId}:${groupId}`
}

function toggleProjectMenu(sectionId: string, groupId: string) {
  closeSessionMenus()
  const key = projectMenuKey(sectionId, groupId)
  openProjectMenuKey.value = openProjectMenuKey.value === key ? null : key
}

function closeProjectMenu() {
  openProjectMenuKey.value = null
}

function handleDocumentPointerDown() {
  closeProjectMenu()
  closeSessionMenus()
}

function handleDocumentKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeProjectMenu()
    closeSessionMenus()
  }
}

function handleDocumentScroll() {
  closeProjectMenu()
  closeSessionMenus()
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeyDown)
  document.addEventListener('scroll', handleDocumentScroll, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeyDown)
  document.removeEventListener('scroll', handleDocumentScroll, true)
})

watch(() => props.activeSessionId, () => {
  closeSessionMenus()
  cancelSessionRename()
})

watch(() => props.projectGroups, () => {
  if (openSessionId.value && !findSession(openSessionId.value)) closeSessionMenus()
  if (editingSessionId.value && !findSession(editingSessionId.value)) cancelSessionRename()
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

function setTransparentDragImage(dataTransfer: DataTransfer): void {
  const dragImage = dragImageRef.value
  if (dragImage) dataTransfer.setDragImage(dragImage, 0, 0)
}

function startProjectDrag(groupId: string, sectionId: string, event: DragEvent): void {
  if (normalizedQuery.value) {
    event.preventDefault()
    return
  }
  dragState.value = { kind: 'project', id: groupId, sectionId }
  dragOverTarget.value = null
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', `project:${groupId}`)
    setTransparentDragImage(event.dataTransfer)
  }
}

function startSessionDrag(groupId: string, sessionId: string, sectionId: string, event: DragEvent): void {
  if (normalizedQuery.value) {
    event.preventDefault()
    return
  }
  dragState.value = { kind: 'session', id: sessionId, groupId, sectionId }
  dragOverTarget.value = null
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', `session:${groupId}:${sessionId}`)
    setTransparentDragImage(event.dataTransfer)
  }
}

function isDragging(
  kind: DragState['kind'],
  id: string,
  groupId?: string,
  sectionId?: string,
): boolean {
  const state = dragState.value
  if (!state || state.kind !== kind || state.id !== id) return false
  if (groupId !== undefined && (!('groupId' in state) || state.groupId !== groupId)) return false
  return sectionId === undefined || state.sectionId === sectionId
}

function handleProjectDragOver(groupId: string, sectionId: string, event: DragEvent): void {
  const state = dragState.value
  if (!state || state.kind !== 'project' || state.sectionId !== sectionId || state.id === groupId) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  setDragOverTarget({
    kind: 'project',
    id: groupId,
    sectionId,
    position: dropPosition(event),
  })
}

function handleSessionDragOver(groupId: string, sessionId: string, sectionId: string, event: DragEvent): void {
  const state = dragState.value
  if (
    !state
    || state.kind !== 'session'
    || state.groupId !== groupId
    || state.sectionId !== sectionId
    || state.id === sessionId
  ) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  setDragOverTarget({
    kind: 'session',
    id: sessionId,
    groupId,
    sectionId,
    position: dropPosition(event),
  })
}

function setDragOverTarget(next: DragOverTarget): void {
  const current = dragOverTarget.value
  if (
    current
    && current.kind === next.kind
    && current.id === next.id
    && current.groupId === next.groupId
    && current.sectionId === next.sectionId
    && current.position === next.position
  ) return
  dragOverTarget.value = next
}

function finishDrag(): void {
  dragState.value = null
  dragOverTarget.value = null
}

function dropProject(groupId: string, sectionId: string): void {
  const state = dragState.value
  if (!state || state.kind !== 'project' || state.sectionId !== sectionId) {
    finishDrag()
    return
  }

  const target = dragOverTarget.value
  const hasPreviewTarget = target?.kind === 'project'
    && target.sectionId === sectionId
    && target.id !== state.id
  const targetId = hasPreviewTarget && target ? target.id : (groupId === state.id ? null : groupId)
  if (!targetId) {
    finishDrag()
    return
  }
  const position = hasPreviewTarget && target ? target.position : 'before'
  const current = normalizeOrder(props.projectGroups.map((group) => group.id), projectOrderIds.value)
  const next = moveId(current, state.id, targetId, position)
  if (next.some((id, index) => id !== current[index])) {
    projectOrderIds.value = next
    persistSidebarOrder('order.projects', next)
  }
  finishDrag()
}

function dropSession(groupId: string, sessionId: string, sectionId: string): void {
  const state = dragState.value
  if (
    !state
    || state.kind !== 'session'
    || state.groupId !== groupId
    || state.sectionId !== sectionId
  ) {
    finishDrag()
    return
  }

  const group = props.projectGroups.find((item) => item.id === groupId)
  if (!group) {
    finishDrag()
    return
  }
  const target = dragOverTarget.value
  const hasPreviewTarget = target?.kind === 'session'
    && target.groupId === groupId
    && target.sectionId === sectionId
    && target.id !== state.id
  const targetId = hasPreviewTarget && target ? target.id : (sessionId === state.id ? null : sessionId)
  if (!targetId) {
    finishDrag()
    return
  }
  const position = hasPreviewTarget && target ? target.position : 'before'
  const current = orderedSessionIds(group)
  const next = moveId(current, state.id, targetId, position)
  if (next.some((id, index) => id !== current[index])) {
    sessionOrderIds.value = { ...sessionOrderIds.value, [groupId]: next }
    persistSidebarOrder('order.sessions', sessionOrderIds.value)
  }
  finishDrag()
}

function orderedSessionIds(group: ProjectGroup): string[] {
  return normalizeOrder(
    group.sessions.map((session) => session.id),
    sessionOrderIds.value[group.id] || [],
  )
}

function previewSessionOrderIds(group: ProjectGroup, sectionId = 'default'): string[] {
  const current = orderedSessionIds(group)
  const state = dragState.value
  const target = dragOverTarget.value
  if (
    !state
    || state.kind !== 'session'
    || state.groupId !== group.id
    || state.sectionId !== sectionId
    || !target
    || target.kind !== 'session'
    || target.groupId !== group.id
    || target.sectionId !== sectionId
  ) return current
  return moveId(current, state.id, target.id, target.position)
}

function orderedSessions(group: ProjectGroup, sectionId = 'default'): SessionItem[] {
  const sessionsById = new Map(group.sessions.map((session) => [session.id, session]))
  return previewSessionOrderIds(group, sectionId).flatMap((id) => {
    const session = sessionsById.get(id)
    return session ? [session] : []
  })
}

function isSessionPinProjection(group: ProjectGroup, sectionId: string): boolean {
  return sectionId === 'pinned' && !isPinned(group.id)
}

function visibleSessions(group: ProjectGroup, sectionId = 'default'): SessionItem[] {
  const ordered = orderedSessions(group, sectionId)
  if (
    isSessionPinProjection(group, sectionId)
    || normalizedQuery.value
    || props.projectSessionLimit <= 0
    || groupExpanded[group.id]
  ) return ordered
  return ordered.slice(0, props.projectSessionLimit)
}

function hiddenCount(group: ProjectGroup, sectionId = 'default'): number {
  if (
    isSessionPinProjection(group, sectionId)
    || normalizedQuery.value
    || props.projectSessionLimit <= 0
    || groupExpanded[group.id]
  ) return 0
  return Math.max(0, orderedSessionIds(group).length - props.projectSessionLimit)
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

function shouldShowStatus(session: SessionItem): boolean {
  const status = session.status?.toLowerCase()
  return status === 'running'
    || status === 'waiting'
    || status === 'pending'
    || status === 'failed'
    || status === 'error'
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
  width: calc(100% - var(--sidebar-indent));
  margin-left: var(--sidebar-indent);
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-backdrop-text) 64%, transparent);
  font-size: 12px;
  text-align: center;
}
.conversation-more:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent);
  color: var(--theme-backdrop-text);
}
.sidebar-project-empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  margin-left: var(--sidebar-indent);
  padding: var(--space-1) var(--space-2);
  color: color-mix(in srgb, var(--theme-backdrop-text) 58%, transparent);
  font-size: 12px;
}
.sidebar-project-empty-action {
  min-height: var(--sidebar-row-height);
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--sidebar-row-radius);
  background: transparent;
  color: var(--theme-backdrop-text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.sidebar-project-empty-action:hover,
.sidebar-project-empty-action:focus-visible {
  background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent);
}
.sidebar-project-empty-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
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
