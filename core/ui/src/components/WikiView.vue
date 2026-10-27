<template>
  <!-- user:“wiki中的UI并没有良好的表现层级关系，建议以左侧以窄栏显示文件层级”+
       左窄栏放 README 的两级目录，正文居中，目录与进度悬浮在右侧。 -->
  <div class="wiki-view library-surface full-area-view" :class="{ 'wiki-view--with-toc': tocItems.length }" data-wiki-view>
    <div v-if="railOpen" class="wiki-scrim" data-wiki-scrim @click="railOpen = false" />

    <!-- ── 左：文件层级（README 分类 → 文章） ── -->
    <aside class="wiki-rail" :class="{ 'wiki-rail--open': railOpen }" data-wiki-rail :aria-label="t('文档导航')">
      <div class="wiki-rail-head">
        <input
          v-model="filter"
          class="wiki-filter"
          type="search"
          :placeholder="t('筛选文档')"
          :aria-label="t('筛选文档')"
          data-wiki-filter
        >
      </div>
      <nav class="wiki-rail-tree">
        <button
          v-if="navigation.index"
          type="button"
          class="wiki-rail-home"
          :class="{ active: activeSlug === navigation.index }"
          :aria-current="activeSlug === navigation.index ? 'page' : undefined"
          data-wiki-index
          @click="go(navigation.index)"
        >
          <BookOpen :size="13" :stroke-width="1.9" aria-hidden="true" />
          <span>{{ t('Wiki 目录') }}</span>
        </button>
        <section v-for="group in visibleGroups" :key="group.id" class="wiki-rail-group" data-wiki-group>
          <button
            type="button"
            class="wiki-rail-group-head"
            :aria-expanded="isExpanded(group.id)"
            data-wiki-group-title
            @click="toggleGroup(group.id)"
          >
            <ChevronRight
              class="wiki-caret"
              :class="{ 'wiki-caret--open': isExpanded(group.id) }"
              :size="13"
              :stroke-width="2"
              aria-hidden="true"
            />
            <span class="wiki-rail-group-name">{{ group.title }}</span>
            <span class="wiki-rail-count">{{ group.entries.length }}</span>
          </button>
          <ul v-show="isExpanded(group.id)" class="wiki-rail-list">
            <li v-for="entry in group.entries" :key="entry.slug">
              <button
                type="button"
                class="wiki-row"
                :class="{ active: entry.slug === activeSlug }"
                :aria-current="entry.slug === activeSlug ? 'page' : undefined"
                :data-wiki-article-item="entry.slug"
                :title="entry.title"
                @click="go(entry.slug)"
              >{{ entry.title }}</button>
            </li>
          </ul>
        </section>
        <p v-if="!visibleGroups.length" class="wiki-rail-empty">{{ t('没有匹配的文档') }}</p>
      </nav>
    </aside>

    <!-- ── 中：正文 ── -->
    <section class="wiki-main">
      <header class="wiki-main-head">
        <button
          v-if="canBack"
          type="button"
          class="wiki-head-btn"
          :title="t('返回')"
          :aria-label="t('返回')"
          data-wiki-back
          @click="back()"
        >
          <ArrowLeft :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="wiki-head-btn wiki-rail-toggle"
          :class="{ active: railOpen }"
          :title="t('文档导航')"
          :aria-label="t('文档导航')"
          :aria-expanded="railOpen"
          data-wiki-rail-toggle
          @click="railOpen = !railOpen"
        >
          <PanelLeft :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <nav class="wiki-crumb" data-wiki-crumb>
          <button type="button" class="wiki-crumb-link" @click="go(navigation.index)">Wiki</button>
          <template v-if="activeGroupTitle">
            <span class="wiki-crumb-sep">/</span>
            <span class="wiki-crumb-group">{{ activeGroupTitle }}</span>
          </template>
          <span class="wiki-crumb-sep">/</span>
          <span class="wiki-crumb-current" data-wiki-active-title>{{ activeTitle || t('Wiki') }}</span>
        </nav>
      </header>

      <div ref="scrollEl" class="wiki-scroll" data-wiki-scroll @scroll.passive="onScroll">
        <article ref="articleEl" class="wiki-article" data-wiki-article @click.capture="onArticleClick">
          <MarkdownRenderer v-if="content" :content="content" :file-references="false" />
          <p v-else-if="errorText" class="wiki-error" data-wiki-error>{{ errorText }}</p>
          <p v-else-if="listLoaded" class="wiki-loading">{{ t('没有可用的文档') }}</p>
          <p v-else class="wiki-loading">{{ t('读取中…') }}</p>
        </article>
      </div>
    </section>

    <!-- ── 右：悬浮目录 + 阅读进度 ── -->
    <aside
      v-if="tocItems.length"
      class="wiki-toc optical-glass optical-glass--low-trans"
      data-wiki-toc
      :aria-label="t('目录')"
    >
      <div class="wiki-toc-head">
        <span>{{ t('目录') }}</span>
        <span class="wiki-toc-percent" data-wiki-progress>{{ percent }}%</span>
      </div>
      <div class="wiki-toc-meter" aria-hidden="true">
        <span :style="{ transform: `scaleX(${progress})` }" />
      </div>
      <nav ref="tocListEl" class="wiki-toc-list">
        <button
          v-for="heading in tocItems"
          :key="heading.id"
          type="button"
          class="wiki-toc-item"
          :class="[`wiki-toc-item--level-${heading.level}`, { active: heading.id === activeHeading }]"
          :data-wiki-toc-item="heading.id"
          :title="heading.text"
          @click="scrollToHeading(heading.id)"
        >{{ heading.text }}</button>
      </nav>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowLeft, BookOpen, ChevronRight, PanelLeft } from 'lucide-vue-next'

import { t } from '@/i18n/index.ts'
import MarkdownRenderer from './MarkdownRenderer.vue'
import {
  collectWikiHeadings,
  isTocHeading,
  normalizeWikiNavigation,
  resolveWikiHref,
  wikiHeadingId,
  wikiScrollProgress,
  type WikiArticleMeta,
  type WikiHeadingEntry,
  type WikiNavigation,
} from './wikiNavigation'

/**
 * Wiki 阅读界面：左栏层级、中间正文、右侧悬浮目录与进度。
 *
 * user:“wiki中的各类链接点击后无法跳转与返回”+文内的 .md 链接与 #小节
 * 锚点都在本界面内解析：链接跳文章、锚点滚到小节、返回键按访问栈回退；
 * 指向仓库源码的链接不是 wiki 内容，拦下导航但不整页跳走。
 */
const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const emit = defineEmits<{
  /** 顶部条标题跟随当前文章。 */
  heading: [payload: { title: string; subtitle: string }]
}>()

interface RailEntry {
  slug: string
  title: string
}

interface RailGroup {
  id: string
  title: string
  entries: RailEntry[]
}

const articles = ref<WikiArticleMeta[]>([])
const navigation = ref<WikiNavigation>({ index: '', groups: [] })
const filter = ref('')
const activeSlug = ref('')
const activeTitle = ref('')
const activeSummary = ref('')
const content = ref('')
const errorText = ref('')
const listLoaded = ref(false)
const headings = ref<WikiHeadingEntry[]>([])
const activeHeading = ref('')
const progress = ref(0)
const expanded = ref(new Set<string>())
const history = ref<string[]>([])
const pendingHash = ref('')
const railOpen = ref(false)
const articleEl = ref<HTMLElement | null>(null)
const scrollEl = ref<HTMLElement | null>(null)
const tocListEl = ref<HTMLElement | null>(null)

const bySlug = computed(() => new Map(articles.value.map(article => [article.slug, article])))

function titleOf(slug: string): string {
  return bySlug.value.get(slug)?.title || slug.split('/').pop() || slug
}

const railGroups = computed<RailGroup[]>(() => navigation.value.groups
  .map(group => ({
    id: group.id,
    title: group.title,
    entries: group.articles
      .filter(slug => bySlug.value.has(slug))
      .map(slug => ({ slug, title: titleOf(slug) })),
  }))
  .filter(group => group.entries.length))

const visibleGroups = computed<RailGroup[]>(() => {
  const needle = filter.value.trim().toLowerCase()
  if (!needle) return railGroups.value
  return railGroups.value
    .map(group => ({
      ...group,
      entries: group.entries.filter((entry) => {
        const meta = bySlug.value.get(entry.slug)
        return entry.title.toLowerCase().includes(needle)
          || entry.slug.toLowerCase().includes(needle)
          || (meta?.summary ?? '').toLowerCase().includes(needle)
      }),
    }))
    .filter(group => group.entries.length)
})

const activeGroup = computed(() => navigation.value.groups.find(group => group.articles.includes(activeSlug.value)) ?? null)
const activeGroupTitle = computed(() => activeGroup.value?.title ?? '')
const canBack = computed(() => history.value.length > 0)
const tocItems = computed(() => headings.value.filter(isTocHeading))
const percent = computed(() => Math.round(progress.value * 100))

function isExpanded(groupId: string): boolean {
  return Boolean(filter.value.trim()) || expanded.value.has(groupId)
}

function toggleGroup(groupId: string): void {
  const next = new Set(expanded.value)
  if (next.has(groupId)) next.delete(groupId)
  else next.add(groupId)
  expanded.value = next
}

/* ── 正文滚动：进度条与当前小节 ── */

let headingTops: Array<{ id: string; top: number }> = []
let headingObserver: MutationObserver | null = null
let sizeObserver: ResizeObserver | null = null

/** 标题相对正文起点的位置；只在这里测量，滚动时不再触发布局。 */
function measureHeadingTops(): void {
  const scroller = scrollEl.value
  if (!scroller) {
    headingTops = []
    return
  }
  const base = scroller.getBoundingClientRect().top - scroller.scrollTop
  headingTops = headings.value.map(heading => ({
    id: heading.id,
    top: heading.element.getBoundingClientRect().top - base,
  }))
}

function updateScrollState(): void {
  const scroller = scrollEl.value
  if (!scroller) return
  progress.value = wikiScrollProgress(scroller.scrollTop, scroller.clientHeight, scroller.scrollHeight)
  if (!headings.value.length) {
    activeHeading.value = ''
    return
  }
  const threshold = scroller.scrollTop + 96
  let current = ''
  for (const item of headingTops) {
    if (item.top <= threshold) current = item.id
    else break
  }
  activeHeading.value = current || headings.value[0]?.id || ''
}

function onScroll(): void {
  // 标题位置已缓存，滚动时只做算术；不为一次滚动再触发布局。
  updateScrollState()
}

/** 目录比界面高时，让当前小节始终留在目录框内。 */
function keepActiveTocItemVisible(id: string): void {
  const list = tocListEl.value
  if (!list || !id) return
  const item = list.querySelector<HTMLElement>(`[data-wiki-toc-item="${id}"]`)
  if (!item) return
  const listRect = list.getBoundingClientRect()
  const itemRect = item.getBoundingClientRect()
  if (itemRect.top < listRect.top) list.scrollTop += itemRect.top - listRect.top
  else if (itemRect.bottom > listRect.bottom) list.scrollTop += itemRect.bottom - listRect.bottom
}

watch(activeHeading, keepActiveTocItemVisible)

function scrollToHeading(id: string, behavior: ScrollBehavior = prefersReducedMotion() ? 'auto' : 'smooth'): void {
  const target = headings.value.find(heading => heading.id === id)
  if (!target) return
  activeHeading.value = id
  const node = target.element
  if (typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'start', behavior })
  else if (scrollEl.value) scrollEl.value.scrollTop = node.offsetTop
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

/** 正文重渲染（或 mermaid/图片改变高度）后重新收集标题与目录。 */
function refreshHeadings(): void {
  const root = articleEl.value?.querySelector<HTMLElement>('.markdown-body')
  headings.value = root ? collectWikiHeadings(root) : []
  measureHeadingTops()
  if (pendingHash.value) {
    const wanted = pendingHash.value
    // 文内锚点按约定省略了标点：先按原样找，再按标题 id 的规则找一次。
    const normalized = wikiHeadingId(wanted)
    const target = headings.value.find(heading => heading.id === wanted
      || heading.text === wanted
      || heading.id === normalized)
    if (target) {
      pendingHash.value = ''
      scrollToHeading(target.id)
      return
    }
  }
  updateScrollState()
}

function observeArticle(): void {
  headingObserver?.disconnect()
  headingObserver = null
  const element = articleEl.value
  if (!element || typeof MutationObserver === 'undefined') return
  headingObserver = new MutationObserver(() => refreshHeadings())
  // 只观察结构变化；补 id 只改属性，不会反过来触发自己。
  headingObserver.observe(element, { childList: true, subtree: true })
  refreshHeadings()
}

function observeSize(): void {
  sizeObserver?.disconnect()
  sizeObserver = null
  if (typeof ResizeObserver === 'undefined') return
  const target = articleEl.value
  if (!target) return
  sizeObserver = new ResizeObserver(() => {
    measureHeadingTops()
    updateScrollState()
  })
  sizeObserver.observe(target)
}

/* ── 打开文章与链接跳转 ── */

async function open(
  slug: string,
  options: { hash?: string; push?: boolean } = {},
): Promise<void> {
  if (!slug) return
  const { hash = '', push = true } = options
  const same = slug === activeSlug.value
  if (same) {
    if (hash) {
      pendingHash.value = hash
      refreshHeadings()
    }
    return
  }
  if (push && activeSlug.value) history.value = [...history.value.slice(-49), activeSlug.value]

  activeSlug.value = slug
  railOpen.value = false
  const meta = bySlug.value.get(slug)
  activeTitle.value = meta?.title ?? titleOf(slug)
  activeSummary.value = meta?.summary ?? ''
  const group = navigation.value.groups.find(item => item.articles.includes(slug))
  if (group && !expanded.value.has(group.id)) expanded.value = new Set([...expanded.value, group.id])

  content.value = ''
  errorText.value = ''
  pendingHash.value = hash
  headings.value = []
  headingTops = []
  progress.value = 0
  activeHeading.value = ''

  try {
    const payload = await props.requestRpc('library.wiki.read', { slug })
    if (activeSlug.value !== slug) return
    activeTitle.value = String(payload.title || activeTitle.value)
    content.value = String(payload.content || '')
  } catch {
    if (activeSlug.value !== slug) return
    errorText.value = t('读取失败')
  }

  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = 0
  refreshHeadings()
}

function go(slug: string): void {
  if (!slug) return
  railOpen.value = false
  void open(slug)
}

/** 返回上一篇文章；没有历史时把「返回」交还给资料库（退出到会话）。 */
function back(): boolean {
  const previous = history.value[history.value.length - 1]
  if (!previous) return false
  history.value = history.value.slice(0, -1)
  void open(previous, { push: false })
  return true
}

/** 文内点击：wiki 链接在界面内跳，源码/外部链接保持原行为。 */
function onArticleClick(event: MouseEvent): void {
  const target = (event.target as HTMLElement | null)?.closest?.('a')
  if (!(target instanceof HTMLAnchorElement)) return
  if (target.dataset.filePath) return
  const href = target.getAttribute('href') ?? ''
  if (!href) return

  const resolved = resolveWikiHref(href, activeSlug.value)
  if (resolved) {
    event.preventDefault()
    event.stopPropagation()
    void open(resolved.slug, { hash: resolved.hash })
    return
  }
  // 指向仓库文件或站外的链接：站外交给 MarkdownRenderer 用系统浏览器打开，
  // 其余相对路径（源码引用）拦下，避免整个应用被 webview 导航走。
  if (/^(?:https?:)?\/\//i.test(href) || /^[a-z][a-z0-9+.-]*:/i.test(href)) return
  event.preventDefault()
  event.stopPropagation()
}

/* ── 装载 ── */

async function loadNavigation(): Promise<void> {
  try {
    const payload = await props.requestRpc('library.wiki.list', {})
    articles.value = Array.isArray(payload.articles) ? payload.articles as WikiArticleMeta[] : []
    navigation.value = normalizeWikiNavigation(payload.navigation, articles.value)
  } catch {
    articles.value = []
    navigation.value = { index: '', groups: [] }
  } finally {
    listLoaded.value = true
  }
  const first = navigation.value.groups[0]
  if (!expanded.value.size && first) expanded.value = new Set([first.id])
}

watch([activeTitle, activeSummary], () => {
  emit('heading', { title: activeTitle.value || t('Wiki'), subtitle: activeSummary.value })
}, { immediate: true })

watch(articleEl, () => {
  observeArticle()
  observeSize()
}, { flush: 'post' })

onMounted(async () => {
  await loadNavigation()
  observeArticle()
  observeSize()
  const start = navigation.value.index || articles.value[0]?.slug || ''
  if (start) await open(start, { push: false })
})

onBeforeUnmount(() => {
  headingObserver?.disconnect()
  sizeObserver?.disconnect()
})

defineExpose({ handleBack: (): boolean => back() })
</script>

<style scoped>
/* 三栏：窄左栏 / 正文 / 悬浮目录。整页高度交给内部各自滚动。
   没有小节的文章不占右侧空栏，正文自然铺满。 */
.wiki-view {
  position: relative;
  display: grid;
  grid-template-columns: 208px minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  padding-top: 0;
  overflow: hidden;
  --text: var(--theme-main-text);
  color: var(--text);
}
.wiki-view--with-toc { grid-template-columns: 208px minmax(0, 1fr) 196px; }

/* ── 左栏：文件层级 ── */
.wiki-rail {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-height: 0;
  padding: var(--space-2) var(--space-2) var(--space-3) var(--space-3);
  border-right: 1px solid color-mix(in srgb, var(--text) 9%, transparent);
}
.wiki-rail-head { flex: 0 0 auto; }
.wiki-filter {
  box-sizing: border-box;
  width: 100%;
  padding: 6px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  font: inherit;
  font-size: 12.5px;
}
.wiki-filter:focus { outline: 0; }
.wiki-filter::placeholder { color: color-mix(in srgb, var(--theme-composer-text) 45%, transparent); }
.wiki-rail-tree {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 1px;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.wiki-rail-home {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--space-1);
  padding: 6px var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 72%, transparent);
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.wiki-rail-home:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.wiki-rail-home.active { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); color: var(--text); }
.wiki-rail-group { display: flex; flex: 0 0 auto; flex-direction: column; gap: 1px; }
.wiki-rail-group-head {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 5px var(--space-1);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 55%, transparent);
  font: inherit;
  font-size: 11.5px;
  font-weight: 650;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.wiki-rail-group-head:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.wiki-caret { flex: 0 0 auto; transition: transform var(--dur-fast) var(--ease-out); }
.wiki-caret--open { transform: rotate(90deg); }
.wiki-rail-group-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wiki-rail-count { margin-left: auto; color: color-mix(in srgb, var(--text) 34%, transparent); font-size: 10.5px; font-variant-numeric: tabular-nums; }
/* 层级线：组内文章缩进并挂在一条竖线上，窄栏里也能一眼看出从属关系。 */
.wiki-rail-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 0 0 var(--space-1) 9px;
  padding: 0 0 0 8px;
  border-left: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  list-style: none;
}
.wiki-row {
  display: block;
  width: 100%;
  padding: 5px 5px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 68%, transparent);
  font: inherit;
  font-size: 12.5px;
  line-height: 1.4;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.wiki-row:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.wiki-row.active { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); color: var(--text); font-weight: 600; }
.wiki-rail-empty { margin: var(--space-3) var(--space-2); font-size: 12px; color: color-mix(in srgb, var(--text) 45%, transparent); }

/* ── 中栏：文章 ── */
.wiki-main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.wiki-main-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
  min-width: 0;
  padding: var(--space-2) var(--space-4) var(--space-2) var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--text) 9%, transparent);
}
.wiki-head-btn {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 72%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.wiki-head-btn:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.wiki-head-btn.active { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); color: var(--text); }
.wiki-crumb {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 55%, transparent);
}
.wiki-crumb-link {
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.wiki-crumb-link:hover { color: var(--text); text-decoration: underline; }
.wiki-crumb-sep { color: color-mix(in srgb, var(--text) 30%, transparent); }
.wiki-crumb-group { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wiki-crumb-current {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--text) 88%, transparent);
  font-weight: 600;
}
.wiki-scroll {
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--space-4) var(--space-5) var(--space-6);
  overflow-y: auto;
  overscroll-behavior: contain;
}
.wiki-article { width: min(100%, 78ch); margin: 0 auto; }
.wiki-article :deep(.markdown-body) { font-size: 14px; line-height: 1.7; }
.wiki-article :deep(h2),
.wiki-article :deep(h3),
.wiki-article :deep(h4) { scroll-margin-top: var(--space-4); }
.wiki-article :deep(> .markdown-body > h1:first-child) { margin-top: 0; }
.wiki-loading,
.wiki-error { margin: 0; font-size: 13px; color: color-mix(in srgb, var(--text) 52%, transparent); }
.wiki-error { color: var(--red); }

/* ── 右栏：悬浮目录与进度 ── */
.wiki-toc {
  display: flex;
  flex-direction: column;
  align-self: start;
  min-height: 0;
  max-height: calc(100% - var(--space-4));
  margin: var(--space-2) var(--space-2) var(--space-2) 0;
  padding: var(--space-2);
  border-radius: var(--radius);
  color: var(--text);
  --optical-glass-surface: var(--theme-main-solid);
}
.wiki-toc-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
  flex: 0 0 auto;
  padding: 0 2px var(--space-1);
  font-size: 11.5px;
  font-weight: 650;
  color: color-mix(in srgb, var(--text) 58%, transparent);
}
.wiki-toc-percent { font-variant-numeric: tabular-nums; color: color-mix(in srgb, var(--text) 78%, transparent); }
.wiki-toc-meter {
  flex: 0 0 auto;
  height: 2px;
  margin: 0 2px var(--space-2);
  border-radius: 999px;
  background: color-mix(in srgb, var(--text) 12%, transparent);
  overflow: hidden;
}
.wiki-toc-meter span {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: inherit;
  background: color-mix(in srgb, var(--text) 62%, transparent);
  transform-origin: left center;
  transition: transform var(--dur-fast) linear;
}
.wiki-toc-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.wiki-toc-item {
  display: block;
  flex: 0 0 auto;
  width: 100%;
  padding: 4px 6px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 55%, transparent);
  font: inherit;
  font-size: 11.5px;
  line-height: 1.45;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.wiki-toc-item:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.wiki-toc-item.active { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); color: var(--text); font-weight: 600; }
.wiki-toc-item--level-3 { padding-left: 16px; font-size: 11px; }
.wiki-toc-item--level-4 { padding-left: 26px; font-size: 11px; }

/* 窄栏在右侧目录放不下时收起；再窄一些左栏改为抽屉。 */
.wiki-rail-toggle { display: none; }
.wiki-scrim { display: none; }
@container app-page (max-width: 1100px) {
  .wiki-view,
  .wiki-view--with-toc { grid-template-columns: 200px minmax(0, 1fr); }
  .wiki-toc { display: none; }
}
@container app-page (max-width: 840px) {
  .wiki-view,
  .wiki-view--with-toc { grid-template-columns: minmax(0, 1fr); }
  .wiki-rail {
    position: absolute;
    inset: 0 auto 0 0;
    z-index: var(--z-popover);
    width: min(268px, 84%);
    padding-top: var(--space-3);
    border-right: 1px solid var(--theme-main-border, color-mix(in srgb, var(--text) 12%, transparent));
    background: var(--theme-main-background);
    box-shadow: var(--shadow-md);
    transform: translateX(-102%);
    transition: transform var(--dur-base) var(--ease-out);
  }
  .wiki-rail--open { transform: none; }
  .wiki-rail-toggle { display: inline-flex; }
  .wiki-scrim {
    display: block;
    position: absolute;
    inset: 0;
    z-index: var(--z-edge-trigger);
    background: color-mix(in srgb, var(--theme-backdrop-text) 20%, transparent);
  }
  .wiki-main-head { padding-left: var(--space-2); }
  .wiki-scroll { padding: var(--space-3) var(--space-3) var(--space-5); }
}

@media (prefers-reduced-motion: reduce) {
  .wiki-rail, .wiki-caret, .wiki-toc-meter span, .wiki-row, .wiki-toc-item, .wiki-rail-home, .wiki-head-btn { transition: none; }
}
</style>
