<template>
  <section class="mobile-chat-list" data-mobile-chat-list aria-label="聊天">
    <header class="mobile-chat-list__head">
      <h1 class="mobile-chat-list__title">{{ t('聊天') }}</h1>
      <div class="mobile-chat-list__actions">
        <button
          type="button"
          class="mobile-chat-list__action"
          :aria-label="query ? t('关闭搜索') : t('搜索会话')"
          :aria-expanded="searchOpen"
          data-mobile-chat-search-toggle
          @click="toggleSearch"
        >
          <Search :size="19" :stroke-width="1.9" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="mobile-chat-list__action"
          :aria-label="t('新建会话')"
          data-mobile-chat-new
          @click="emit('create')"
        >
          <Plus :size="20" :stroke-width="2" aria-hidden="true" />
        </button>
      </div>
    </header>

    <!-- user:“项目不应该和环境放在一个选项内”+(这一行只说运行在哪台设备上，点它只换环境；
         项目是下面可折叠的分组标题，不再和环境挤进同一个入口)。 -->
    <button
      type="button"
      class="mobile-chat-list__context"
      data-mobile-chat-environment
      @click="emit('pick-environment')"
    >
      <MonitorSmartphone :size="14" :stroke-width="1.8" aria-hidden="true" />
      <span class="mobile-chat-list__env">{{ props.environmentName || t('本机 Android') }}</span>
      <ChevronDown :size="13" :stroke-width="2" aria-hidden="true" />
    </button>

    <label v-show="searchOpen" class="mobile-chat-list__search">
      <Search :size="15" :stroke-width="1.9" aria-hidden="true" />
      <input
        ref="searchEl"
        v-model="query"
        type="search"
        :placeholder="t('搜索会话')"
        :aria-label="t('搜索会话')"
        data-mobile-chat-search
      >
    </label>

    <div class="mobile-chat-list__scroll">
      <template v-if="pinnedEntries.length">
        <h2 class="mobile-chat-list__section">{{ t('置顶') }}</h2>
        <div v-for="entry in pinnedEntries" :key="`pin-${entry.id}`" class="mobile-chat-row">
          <button
            type="button"
            class="mobile-chat-card"
            :class="{ 'is-active': entry.id === props.activeSessionId }"
            :data-mobile-chat-session="entry.id"
            @click="openEntry(entry.id)"
            @pointerdown="startPress(entry.id, $event)"
            @pointerup="cancelPress"
            @pointerleave="cancelPress"
            @pointercancel="cancelPress"
            @contextmenu.prevent="emit('session-menu', entry.id, $event)"
          >
            <span class="mobile-chat-card__avatar" aria-hidden="true">{{ entry.initial }}</span>
            <span class="mobile-chat-card__body">
              <span class="mobile-chat-card__title">{{ entry.title }}</span>
              <span class="mobile-chat-card__sub">{{ entry.projectName }} · {{ entry.subtitle }}</span>
            </span>
            <span class="mobile-chat-card__time">{{ entry.time }}</span>
          </button>
          <button
            type="button"
            class="mobile-chat-row__more"
            :aria-label="t('会话操作')"
            :title="t('会话操作')"
            :data-mobile-session-more="entry.id"
            @click.stop="emit('session-menu', entry.id, $event)"
          >
            <MoreHorizontal :size="16" :stroke-width="2" aria-hidden="true" />
          </button>
        </div>
      </template>

      <!-- user:“可以折叠掉会话的父级标签…这个抽屉就是项目”+(每个项目一条可折叠标题：
           轻点收起/展开；右侧 ⋯ 是项目菜单（项目设置/重命名/删除），＋ 是在这一组里新建会话)。
           user:“项目设置和‘更多’在哪里去进入？”+(不再藏在长按里，⋯ 常显)。 -->
      <section
        v-for="group in visibleGroups"
        :key="group.id"
        class="mobile-chat-group"
        :data-mobile-chat-group="group.id"
      >
        <div class="mobile-chat-group__bar">
          <button
            type="button"
            class="mobile-chat-group__head"
            :data-mobile-chat-group-head="group.id"
            :aria-expanded="!isCollapsed(group.id)"
            @click="toggleGroup(group.id)"
            @pointerdown="startGroupPress(group.id, $event)"
            @pointerup="cancelGroupPress"
            @pointerleave="cancelGroupPress"
            @pointercancel="cancelGroupPress"
            @contextmenu.prevent="emit('project-menu', group.id, $event)"
          >
            <ChevronRight
              class="mobile-chat-group__chevron"
              :class="{ 'is-open': !isCollapsed(group.id) }"
              :size="15"
              :stroke-width="2"
              aria-hidden="true"
            />
            <span class="mobile-chat-group__name">{{ group.name || t('未命名项目') }}</span>
            <span v-if="group.id === props.activeProjectId" class="mobile-chat-group__current">{{ t('当前') }}</span>
            <span class="mobile-chat-group__count">{{ groupSessions(group).length }}</span>
          </button>
          <button
            type="button"
            class="mobile-chat-group__more"
            :aria-label="t('在「{0}」里新建会话', { 0: group.name || t('未命名项目') })"
            :title="t('新建会话')"
            :data-mobile-project-new="group.id"
            @click.stop="emit('create-session', group.id)"
          >
            <Plus :size="17" :stroke-width="2" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="mobile-chat-group__more"
            :aria-label="t('项目设置')"
            :title="t('项目设置')"
            :data-mobile-project-more="group.id"
            @click.stop="emit('project-menu', group.id, $event)"
          >
            <MoreHorizontal :size="16" :stroke-width="2" aria-hidden="true" />
          </button>
        </div>

        <template v-if="!isCollapsed(group.id)">
          <div v-for="entry in groupSessions(group)" :key="entry.id" class="mobile-chat-row">
            <button
              type="button"
              class="mobile-chat-card"
              :class="{ 'is-active': entry.id === props.activeSessionId }"
              :data-mobile-chat-session="entry.id"
              @click="openEntry(entry.id)"
              @pointerdown="startPress(entry.id, $event)"
              @pointerup="cancelPress"
              @pointerleave="cancelPress"
              @pointercancel="cancelPress"
              @contextmenu.prevent="emit('session-menu', entry.id, $event)"
            >
              <span class="mobile-chat-card__avatar" aria-hidden="true">{{ entry.initial }}</span>
              <span class="mobile-chat-card__body">
                <span class="mobile-chat-card__title">{{ entry.title }}</span>
                <span class="mobile-chat-card__sub" :data-status="entry.status || undefined">{{ entry.subtitle }}</span>
              </span>
              <span class="mobile-chat-card__time">{{ entry.time }}</span>
              <span v-if="entry.running" class="mobile-chat-card__dot" aria-hidden="true"></span>
            </button>
            <button
              type="button"
              class="mobile-chat-row__more"
              :aria-label="t('会话操作')"
              :title="t('会话操作')"
              :data-mobile-session-more="entry.id"
              @click.stop="emit('session-menu', entry.id, $event)"
            >
              <MoreHorizontal :size="16" :stroke-width="2" aria-hidden="true" />
            </button>
          </div>
          <p v-if="!groupSessions(group).length" class="mobile-chat-group__empty">{{ t('还没有会话') }}</p>
        </template>
      </section>

      <p v-if="!visibleGroups.length" class="mobile-chat-list__empty">
        {{ query ? t('没有匹配的会话') : (props.groups.length ? t('还没有会话') : t('还没有项目')) }}
      </p>

      <button
        type="button"
        class="mobile-chat-list__new-project"
        data-mobile-chat-create-project
        @click="emit('create-project')"
      >
        <Plus :size="15" :stroke-width="2" aria-hidden="true" />
        {{ t('新建项目') }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { ChevronDown, ChevronRight, MonitorSmartphone, MoreHorizontal, Plus, Search } from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'

/**
 * user:“聊天优先：用户首先看到会话”+“首页从上到下：标题、搜索、新建、置顶、普通会话”+
 * (L1 会话列表：WeChat 式单列卡片，头像 + 名称 + 状态/时间；置顶与全部两段；
 *  只消费现有会话数据，最后一条消息摘要与未读数是后端缺口，先用状态文案占位)。
 */
interface SessionLike {
  id: string
  title?: string
  updatedAt?: string
  status?: string
}
interface GroupLike {
  id: string
  name?: string
  sessions: SessionLike[]
}

const props = defineProps<{
  groups: GroupLike[]
  activeSessionId?: string
  /** 当前项目：只在它的分组标题上标「当前」，切换项目靠打开该项目的会话。 */
  activeProjectId?: string
  pinKey?: string
  /** 置顶会话（由宿主持有并持久化，列表只负责分组与展示）。 */
  pinnedSessionIds?: string[]
  /** 环境名（本机 Android / 电脑 · 已连接）；和项目分开展示。 */
  environmentName?: string
}>()
const emit = defineEmits<{
  open: [sessionId: string]
  create: []
  'pick-environment': []
  'create-project': []
  /** 用户在某条项目标题上点「+」：在那一组里新建会话。 */
  'create-session': [projectId: string]
  'session-menu': [sessionId: string, event: Event]
  'project-menu': [projectId: string, event: Event]
}>()

// user:“项目设置和‘更多’在哪里去进入？”+(长按菜单保留为快捷手势，但长按抬手之后浏览器还会补发
// 一次 click；那一下必须丢掉，否则菜单刚弹出就把会话打开了、或把项目折叠了。)
const suppressClickUntil = ref(0)
function longPressFired(): void {
  suppressClickUntil.value = Date.now() + 700
}
function clickSuppressed(): boolean {
  return Date.now() < suppressClickUntil.value
}

// user:“长按置顶、重命名、归档、删除等操作”+
// (卡片长按 450ms 弹会话菜单；指针一移动/抬起就取消，不影响轻点打开)。
let pressTimer: ReturnType<typeof setTimeout> | null = null
function cancelPress(): void {
  if (pressTimer !== null) {
    clearTimeout(pressTimer)
    pressTimer = null
  }
}
function startPress(sessionId: string, event: PointerEvent): void {
  cancelPress()
  pressTimer = setTimeout(() => {
    pressTimer = null
    longPressFired()
    emit('session-menu', sessionId, event)
  }, 450)
}
onBeforeUnmount(cancelPress)

const searchOpen = ref(false)
const query = ref('')
const searchEl = ref<HTMLInputElement | null>(null)

function toggleSearch() {
  searchOpen.value = !searchOpen.value
  if (searchOpen.value) {
    void nextTick(() => searchEl.value?.focus())
  } else {
    query.value = ''
  }
}

// 宿主给了置顶列表就以它为准（置顶/取消置顶后立刻重排）；没给才回落到本地存储。
const pinnedIds = computed(() => {
  if (props.pinnedSessionIds) return new Set(props.pinnedSessionIds)
  if (!props.pinKey || typeof localStorage === 'undefined') return new Set<string>()
  try {
    const raw = JSON.parse(localStorage.getItem(`${props.pinKey}.sessions`) || '[]')
    return new Set(Array.isArray(raw) ? raw.filter((id): id is string => typeof id === 'string') : [])
  } catch {
    return new Set<string>()
  }
})

interface Entry {
  id: string
  title: string
  projectId: string
  projectName: string
  subtitle: string
  initial: string
  time: string
  status?: string
  running: boolean
}

function relativeTime(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  if (sameDay) return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) return t('昨天')
  return `${date.getMonth() + 1}/${date.getDate()}`
}

function statusText(status?: string): string {
  const value = (status || '').toLowerCase()
  if (value === 'running') return t('正在执行')
  if (value === 'waiting' || value === 'pending') return t('等待你确认')
  if (value === 'sub_agents') return t('子代理执行中')
  if (value === 'paused') return t('已暂停')
  if (value === 'failed' || value === 'error') return t('执行失败')
  return ''
}

const allEntries = computed<Entry[]>(() => {
  const list: Entry[] = []
  for (const group of props.groups || []) {
    for (const session of group.sessions || []) {
      const title = (session.title || '').trim() || t('新会话')
      list.push({
        id: session.id,
        title,
        projectId: group.id,
        projectName: group.name || t('未命名项目'),
        subtitle: statusText(session.status) || (relativeTime(session.updatedAt) ? t('最近活动') : t('暂无消息')),
        // user:“左：头像，区分 Agent、用户和系统会话”+(没有 Agent 数据时用会话名首字，
        // 全用项目名首字会让每个头像都长得一样，反而分不清会话)。
        initial: (title || group.name || '?').slice(0, 1).toUpperCase(),
        time: relativeTime(session.updatedAt),
        status: session.status,
        running: statusText(session.status) !== '',
      })
    }
  }
  return list.sort((a, b) => (b.time > a.time ? 1 : -1))
})

function matches(entry: Entry): boolean {
  const value = query.value.trim().toLowerCase()
  if (!value) return true
  return entry.title.toLowerCase().includes(value)
}

const pinnedEntries = computed(() => allEntries.value.filter(entry => pinnedIds.value.has(entry.id) && matches(entry)))

// user:“可以折叠掉会话的父级标签”+(折叠状态按项目记在本地：收起哪个项目就一直是收起的，
// 直到用户自己再展开；搜索时强制展开，否则搜到了却看不见)。
const collapsedIds = ref<string[]>(loadCollapsedIds())
function loadCollapsedIds(): string[] {
  if (typeof localStorage === 'undefined' || !props.pinKey) return []
  try {
    const raw = JSON.parse(localStorage.getItem(`${props.pinKey}.collapsed-projects`) || '[]')
    return Array.isArray(raw) ? raw.filter((id): id is string => typeof id === 'string') : []
  } catch {
    return []
  }
}
function persistCollapsedIds(): void {
  if (typeof localStorage === 'undefined' || !props.pinKey) return
  try {
    localStorage.setItem(`${props.pinKey}.collapsed-projects`, JSON.stringify(collapsedIds.value))
  } catch {
    // 存储不可用就只在本次运行里保持折叠，不影响会话数据本身。
  }
}
function isCollapsed(projectId: string): boolean {
  if (query.value.trim()) return false
  return collapsedIds.value.includes(projectId)
}
function openEntry(sessionId: string): void {
  if (clickSuppressed()) return
  emit('open', sessionId)
}
function toggleGroup(projectId: string): void {
  if (clickSuppressed()) return
  collapsedIds.value = collapsedIds.value.includes(projectId)
    ? collapsedIds.value.filter(id => id !== projectId)
    : [...collapsedIds.value, projectId]
  persistCollapsedIds()
}
function groupSessions(group: GroupLike): Entry[] {
  return allEntries.value.filter(entry => entry.projectId === group.id && !pinnedIds.value.has(entry.id) && matches(entry))
}
const visibleGroups = computed(() => props.groups.filter(group =>
  !query.value.trim() || groupSessions(group).length > 0,
))

let groupPressTimer: ReturnType<typeof setTimeout> | null = null
function cancelGroupPress(): void {
  if (groupPressTimer !== null) {
    clearTimeout(groupPressTimer)
    groupPressTimer = null
  }
}
// 轻点是收起/展开，长按才是项目菜单：两种手势不能互相抢。
function startGroupPress(projectId: string, event: PointerEvent): void {
  cancelGroupPress()
  groupPressTimer = setTimeout(() => {
    groupPressTimer = null
    longPressFired()
    emit('project-menu', projectId, event)
  }, 450)
}
onBeforeUnmount(cancelGroupPress)
</script>

<style scoped>
.mobile-chat-list {
  position: fixed;
  inset: var(--native-safe-area-top, 0px) 0 calc(var(--mobile-bottom-nav-height, 56px) + var(--safe-area-bottom)) 0;
  z-index: var(--z-main-surface);
  display: flex;
  flex-direction: column;
  background: var(--theme-main-background);
  color: var(--theme-main-text);
}

.mobile-chat-list__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: 10px var(--space-4) 6px;
}

.mobile-chat-list__title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
}

.mobile-chat-list__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.mobile-chat-list__action {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-chat-list__action:active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

/* user:“建议顶部结构：本机 Android / 默认项目 ▾”+(一行上下文，点开环境与项目面板)。 */
.mobile-chat-list__context {
  display: flex;
  align-items: center;
  gap: 4px;
  align-self: flex-start;
  max-width: calc(100% - var(--space-4) * 2);
  margin: 0 var(--space-4) 8px;
  padding: 4px 10px;
  border: 0;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text) 7%, transparent);
  color: color-mix(in srgb, var(--theme-main-text) 72%, transparent);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-chat-list__env {
  color: color-mix(in srgb, var(--theme-main-text) 52%, transparent);
}

.mobile-chat-list__context-sep {
  color: color-mix(in srgb, var(--theme-main-text) 32%, transparent);
}

.mobile-chat-list__project {
  max-width: 42vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--theme-main-text);
  font-weight: 600;
}

.mobile-chat-list__search {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 var(--space-4) 6px;
  padding: 0 var(--space-3);
  height: 40px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text) 7%, transparent);
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
}

.mobile-chat-list__search input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--theme-main-text);
  font: inherit;
  font-size: 14px;
}

.mobile-chat-list__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 var(--space-3) var(--space-4);
  -webkit-overflow-scrolling: touch;
}

.mobile-chat-list__section {
  margin: var(--space-3) var(--space-1) var(--space-1);
  color: color-mix(in srgb, var(--theme-main-text) 55%, transparent);
  font-size: 12px;
  font-weight: 600;
}

.mobile-chat-card {
  position: relative;
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: 64px;
  padding: 8px var(--space-2);
  /* 卡片是整行按钮：宽度含内边距，不然右边的时间会被滚动容器裁掉。 */
  box-sizing: border-box;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-chat-card:active,
.mobile-chat-card.is-active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

.mobile-chat-card__avatar {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  color: var(--theme-main-text);
  font-size: 16px;
  font-weight: 600;
}

.mobile-chat-card__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.mobile-chat-card__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 600;
}

.mobile-chat-card__sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
}

.mobile-chat-card__sub[data-status='running'],
.mobile-chat-card__sub[data-status='sub_agents'] {
  color: var(--green);
}

.mobile-chat-card__sub[data-status='waiting'],
.mobile-chat-card__sub[data-status='pending'] {
  color: var(--orange);
}

.mobile-chat-card__sub[data-status='failed'],
.mobile-chat-card__sub[data-status='error'] {
  color: var(--red);
}

.mobile-chat-card__time {
  align-self: start;
  margin-top: 2px;
  color: color-mix(in srgb, var(--theme-main-text) 46%, transparent);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.mobile-chat-card__dot {
  position: absolute;
  right: 10px;
  bottom: 12px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
}

/* 每行 = 会话卡片 + 右侧 ⋯；⋯ 常显，长按只是快捷方式。 */
.mobile-chat-row {
  display: flex;
  align-items: stretch;
  gap: 2px;
}

.mobile-chat-row > .mobile-chat-card {
  flex: 1 1 auto;
  min-width: 0;
}

.mobile-chat-row__more,
.mobile-chat-group__more {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 38px;
  min-height: 38px;
  align-self: center;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-chat-row__more:active,
.mobile-chat-group__more:active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

.mobile-chat-group__bar {
  display: flex;
  align-items: center;
  gap: 2px;
}

.mobile-chat-group__bar > .mobile-chat-group__head {
  flex: 1 1 auto;
  min-width: 0;
}

/* 项目分组：一条可折叠的父级标题，会话挂在它下面。 */
.mobile-chat-group {
  margin-top: var(--space-2);
}

.mobile-chat-group__head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 36px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 78%, transparent);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-chat-group__head:active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

.mobile-chat-group__chevron {
  flex: 0 0 auto;
  transition: transform .16s ease;
}

.mobile-chat-group__chevron.is-open {
  transform: rotate(90deg);
}

.mobile-chat-group__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-chat-group__current {
  flex: 0 0 auto;
  padding: 1px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  color: color-mix(in srgb, var(--theme-main-text) 70%, transparent);
  font-size: 10px;
  font-weight: 500;
}

.mobile-chat-group__count {
  flex: 0 0 auto;
  margin-left: auto;
  color: color-mix(in srgb, var(--theme-main-text) 40%, transparent);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.mobile-chat-group__empty {
  margin: 2px var(--space-2) var(--space-1);
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  font-size: 12px;
}

.mobile-chat-list__new-project {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  min-height: 44px;
  margin: var(--space-4) 0 var(--space-2);
  box-sizing: border-box;
  border: 1px dashed color-mix(in srgb, var(--theme-main-text) 22%, transparent);
  border-radius: var(--radius);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 70%, transparent);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.mobile-chat-list__empty {
  margin: var(--space-6) 0;
  text-align: center;
  color: color-mix(in srgb, var(--theme-main-text) 50%, transparent);
  font-size: 13px;
}
</style>
