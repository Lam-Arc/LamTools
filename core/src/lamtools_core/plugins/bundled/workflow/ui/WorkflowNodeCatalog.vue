<template>
  <section
    class="wf-catalog"
    :class="{ 'wf-catalog-popover': variant === 'popover' }"
    data-workflow-node-catalog
    aria-label="工作流节点目录"
  >
    <header class="wf-catalog-head">
      <div>
        <h3>节点目录</h3>
        <span class="wf-catalog-count">{{ filteredSchemas.length }} 个节点</span>
      </div>
      <div class="wf-catalog-head-actions">
        <button
          v-if="variant !== 'popover' || search"
          class="wf-icon-btn"
          type="button"
          aria-label="清除节点目录搜索"
          title="清除搜索"
          :disabled="!search"
          @click="search = ''"
        >×</button>
        <button
          v-if="closeable"
          class="wf-icon-btn wf-catalog-close"
          type="button"
          aria-label="关闭节点目录"
          title="关闭"
          @click="emit('close')"
        >×</button>
      </div>
    </header>
    <label class="wf-catalog-search">
      <span class="sr-only">搜索节点</span>
      <input ref="searchInput" v-model="search" type="search" placeholder="搜索名称、分类或说明" autocomplete="off" />
    </label>
    <div class="wf-catalog-filters" role="toolbar" aria-label="节点目录筛选">
      <button
        v-for="filter in filters"
        :key="filter.value"
        type="button"
        class="wf-filter-btn"
        :class="{ active: scope === filter.value }"
        :aria-pressed="scope === filter.value"
        @click="scope = filter.value"
      >{{ filter.label }}</button>
    </div>
    <div v-if="categories.length > 1" class="wf-catalog-categories" role="toolbar" aria-label="节点分类">
      <button
        v-for="category in categories"
        :key="category"
        type="button"
        class="wf-category-btn"
        :class="{ active: categoryFilter === category }"
        :aria-pressed="categoryFilter === category"
        @click="categoryFilter = category"
      >{{ categoryLabel(category) }}</button>
    </div>
    <ul v-if="filteredSchemas.length" class="wf-catalog-list">
      <li v-for="schema in filteredSchemas" :key="schemaKey(schema)" class="wf-catalog-item">
        <button
          type="button"
          class="wf-catalog-add"
          :aria-label="`添加节点：${schemaLabel(schema)}`"
          :title="schema.description || schemaLabel(schema)"
          @click="addSchema(schema)"
          @keydown.enter.prevent="addSchema(schema)"
          @keydown.space.prevent="addSchema(schema)"
        >
          <span class="wf-catalog-glyph" aria-hidden="true">{{ categoryGlyph(schema.category) }}</span>
          <span class="wf-catalog-copy">
            <strong>{{ schemaLabel(schema) }}</strong>
            <small>{{ schema.category || 'workflow' }}</small>
          </span>
          <span class="wf-catalog-plus" aria-hidden="true">+</span>
        </button>
        <button
          type="button"
          class="wf-catalog-favorite"
          :class="{ active: isFavorite(schema) }"
          :aria-label="isFavorite(schema) ? `取消收藏：${schemaLabel(schema)}` : `收藏：${schemaLabel(schema)}`"
          :aria-pressed="isFavorite(schema)"
          @click="toggleFavorite(schema)"
        >{{ isFavorite(schema) ? '★' : '☆' }}</button>
      </li>
    </ul>
    <p v-else class="wf-catalog-empty">没有匹配的节点</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  workflowCatalogEntries,
  readWorkflowCatalogPreferences,
  recordWorkflowCatalogRecent,
  toggleWorkflowCatalogFavorite,
  writeWorkflowCatalogPreferences,
  type WorkflowCatalogVariant,
} from './catalog'
import type { WorkflowNodeSchema } from './types'

const props = withDefaults(defineProps<{
  schemas?: Record<string, WorkflowNodeSchema>
  variant?: WorkflowCatalogVariant
  closeable?: boolean
}>(), {
  schemas: () => ({}),
  variant: 'sidebar',
  closeable: false,
})
const emit = defineEmits<{
  add: [schema: WorkflowNodeSchema]
  close: []
}>()

type Scope = 'all' | 'recent' | 'favorites'
const search = ref('')
const scope = ref<Scope>('all')
const categoryFilter = ref('全部')
const preferences = ref(readWorkflowCatalogPreferences())
const searchInput = ref<HTMLInputElement | null>(null)
const filters: Array<{ value: Scope; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'recent', label: '最近' },
  { value: 'favorites', label: '收藏' },
]

const schemaList = computed(() => {
  const visible = workflowCatalogEntries(props.schemas)
  // A registry-less/old host may expose only the compatibility `ai` entry.
  // Keep that degraded catalog usable while hiding it whenever a modern entry
  // is available. Existing documents are never filtered by this component.
  return visible.length ? visible : workflowCatalogEntries(props.schemas, { includeHidden: true })
})

const categories = computed(() => {
  const values = new Set(schemaList.value.map(({ schema }) => String(schema.category || 'workflow')))
  return ['全部', ...[...values].sort((a, b) => a.localeCompare(b))]
})

const filteredSchemas = computed(() => {
  const query = search.value.trim().toLowerCase()
  return schemaList.value
    .filter(({ key, schema }) => {
      const id = schemaKey(schema, key)
      if (scope.value === 'recent' && !preferences.value.recent.includes(id)) return false
      if (scope.value === 'favorites' && !preferences.value.favorites.includes(id)) return false
      const category = String(schema.category || 'workflow')
      if (categoryFilter.value !== '全部' && category !== categoryFilter.value) return false
      if (!query) return true
      return [
        id,
        schemaLabel(schema),
        schema.description,
        category,
        ...(Array.isArray(schema.tags) ? schema.tags : []),
        ...(Array.isArray(schema.keywords) ? schema.keywords : []),
      ].some((value) => String(value || '').toLowerCase().includes(query))
    })
    .sort((a, b) => {
      const aId = schemaKey(a.schema, a.key)
      const bId = schemaKey(b.schema, b.key)
      const aRecent = preferences.value.recent.indexOf(aId)
      const bRecent = preferences.value.recent.indexOf(bId)
      if (scope.value === 'recent' && aRecent !== bRecent) return (aRecent < 0 ? 999 : aRecent) - (bRecent < 0 ? 999 : bRecent)
      const aFavorite = preferences.value.favorites.includes(aId)
      const bFavorite = preferences.value.favorites.includes(bId)
      if (aFavorite !== bFavorite) return aFavorite ? -1 : 1
      return schemaLabel(a.schema).localeCompare(schemaLabel(b.schema))
    })
    .map(({ schema }) => schema)
})

function schemaKey(schema: WorkflowNodeSchema, fallback = ''): string {
  return String(schema.type_id ?? schema.name ?? fallback).trim()
}

function schemaLabel(schema: WorkflowNodeSchema): string {
  return String(schema.display_name ?? schema.title ?? schema.name ?? '未命名节点')
}

function categoryLabel(category: string): string {
  if (category === '全部') return category
  return category.replace(/^workflow\//, '')
}

function categoryGlyph(category?: string): string {
  const value = String(category || '')
  if (value.includes('ai')) return '✦'
  if (value.includes('runtime')) return '↯'
  if (value.includes('data')) return '◇'
  if (value.includes('composition')) return '⊕'
  return '◈'
}

function isFavorite(schema: WorkflowNodeSchema): boolean {
  return preferences.value.favorites.includes(schemaKey(schema))
}

function addSchema(schema: WorkflowNodeSchema): void {
  const key = schemaKey(schema)
  preferences.value = recordWorkflowCatalogRecent(preferences.value, key)
  writeWorkflowCatalogPreferences(preferences.value)
  emit('add', schema)
}

function toggleFavorite(schema: WorkflowNodeSchema): void {
  preferences.value = toggleWorkflowCatalogFavorite(preferences.value, schemaKey(schema))
  writeWorkflowCatalogPreferences(preferences.value)
}

onMounted(() => {
  if (props.closeable) searchInput.value?.focus()
})
</script>

<style scoped>
.wf-catalog { display: grid; gap: var(--space-2); padding: var(--space-3); border-bottom: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); color: var(--theme-backdrop-text); }
.wf-catalog-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.wf-catalog-head-actions { display: flex; align-items: center; gap: var(--space-1); }
.wf-catalog-head h3 { margin: 0; font-size: 12px; font-weight: 700; }
.wf-catalog-count { display: block; margin-top: 2px; color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); font-size: 10px; }
.wf-icon-btn { width: 28px; height: 28px; border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 62%, transparent); cursor: pointer; font-size: 17px; line-height: 1; }
.wf-icon-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); color: var(--theme-backdrop-text); }
.wf-icon-btn:disabled { opacity: .35; cursor: default; }
.wf-catalog-search input { width: 100%; box-sizing: border-box; min-height: 32px; border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); padding: 0 var(--space-2); outline: 0; font: inherit; font-size: 11px; }
.wf-catalog-filters, .wf-catalog-categories { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.wf-filter-btn, .wf-category-btn { min-height: 26px; border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 60%, transparent); padding: 0 var(--space-2); cursor: pointer; font-size: 10px; }
.wf-filter-btn:hover, .wf-category-btn:hover { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); color: var(--theme-backdrop-text); }
.wf-filter-btn.active, .wf-category-btn.active { background: color-mix(in srgb, var(--blue) 20%, transparent); color: var(--theme-backdrop-text); }
.wf-catalog-categories { max-height: 58px; overflow: auto; }
.wf-catalog-list { display: grid; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.wf-catalog-item { display: flex; min-width: 0; align-items: stretch; }
.wf-catalog-add { flex: 1 1 auto; min-width: 0; display: flex; align-items: center; gap: var(--space-2); border: 0; border-radius: var(--radius-sm) 0 0 var(--radius-sm); background: transparent; color: var(--theme-backdrop-text); padding: var(--space-1) var(--space-2); text-align: left; cursor: pointer; }
.wf-catalog-add:hover, .wf-catalog-add:focus-visible { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); outline: 0; }
.wf-catalog-glyph { flex: 0 0 auto; width: 20px; color: var(--blue); text-align: center; }
.wf-catalog-copy { min-width: 0; display: grid; gap: 2px; }
.wf-catalog-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 600; }
.wf-catalog-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: color-mix(in srgb, var(--theme-backdrop-text) 45%, transparent); font-size: 9px; }
.wf-catalog-plus { margin-left: auto; color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); font-size: 15px; }
.wf-catalog-favorite { flex: 0 0 32px; border: 0; border-radius: 0 var(--radius-sm) var(--radius-sm) 0; background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); cursor: pointer; font-size: 15px; }
.wf-catalog-favorite:hover, .wf-catalog-favorite:focus-visible { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); outline: 0; }
.wf-catalog-favorite.active { color: var(--orange); }
.wf-catalog-empty { margin: 0; color: color-mix(in srgb, var(--theme-backdrop-text) 44%, transparent); font-size: 11px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.wf-catalog-popover {
  min-width: min(340px, calc(100vw - var(--space-4)));
  max-width: min(380px, calc(100vw - var(--space-4)));
  max-height: min(620px, calc(100vh - var(--space-4)));
  overflow: auto;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--theme-main-background) 90%, transparent);
  color: var(--theme-main-text);
  box-shadow: var(--shadow-md);
  -webkit-backdrop-filter: blur(var(--space-2)) saturate(1.2);
  backdrop-filter: blur(var(--space-2)) saturate(1.2);
}
.wf-catalog-popover .wf-catalog-count,
.wf-catalog-popover .wf-catalog-copy small,
.wf-catalog-popover .wf-catalog-empty { color: color-mix(in srgb, var(--theme-main-text) 48%, transparent); }
.wf-catalog-popover .wf-icon-btn,
.wf-catalog-popover .wf-filter-btn,
.wf-catalog-popover .wf-category-btn,
.wf-catalog-popover .wf-catalog-add,
.wf-catalog-popover .wf-catalog-favorite { color: var(--theme-main-text); }
.wf-catalog-popover .wf-filter-btn:hover,
.wf-catalog-popover .wf-category-btn:hover,
.wf-catalog-popover .wf-catalog-add:hover,
.wf-catalog-popover .wf-catalog-add:focus-visible,
.wf-catalog-popover .wf-catalog-favorite:hover,
.wf-catalog-popover .wf-catalog-favorite:focus-visible,
.wf-catalog-popover .wf-icon-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); }
.wf-catalog-popover .wf-filter-btn.active,
.wf-catalog-popover .wf-category-btn.active { background: color-mix(in srgb, var(--blue) 20%, transparent); }
.wf-catalog-popover .wf-catalog-search input { background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); }
@media (max-width: 640px) { .wf-filter-btn, .wf-category-btn, .wf-catalog-favorite, .wf-icon-btn { min-height: 44px; } .wf-catalog-favorite { flex-basis: 44px; } }
@media (prefers-reduced-motion: reduce) { .wf-catalog *, .wf-catalog { transition: none; animation: none; } }
</style>
