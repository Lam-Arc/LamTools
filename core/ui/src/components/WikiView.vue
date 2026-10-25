<template>
  <div class="wiki-view library-surface full-area-view">
    <header v-if="!activeSlug" class="wiki-head">
      <h2>{{ t('Wiki') }}</h2>
      <p class="wiki-sub">{{ t('随版本内置的说明文档 — 与当前运行版本一致') }}</p>
      <input v-model="filter" class="wiki-filter" type="text" :placeholder="t('筛选标题与摘要')" />
    </header>

    <div v-if="!activeSlug" class="wiki-list" role="list">
      <button
        v-for="article in filtered"
        :key="article.slug"
        type="button"
        role="listitem"
        class="wiki-row"
        @click="open(article.slug)"
      >
        <strong>{{ article.title }}</strong>
        <span v-if="article.summary" class="wiki-summary">{{ article.summary }}</span>
      </button>
      <p v-if="!filtered.length" class="wiki-empty">{{ t('没有匹配的文档') }}</p>
    </div>

    <article v-else class="wiki-article">
      <div class="wiki-article-head">
        <button class="text-btn" type="button" @click="activeSlug = ''">{{ t('返回列表') }}</button>
        <h2>{{ activeTitle }}</h2>
      </div>
      <MarkdownRenderer :content="activeContent" />
    </article>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { t } from '@/i18n/index.ts'
import MarkdownRenderer from './MarkdownRenderer.vue'

interface WikiArticle {
  slug: string
  title: string
  summary: string
  section: string
  size: number
}

const props = defineProps<{ requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>> }>()

const articles = ref<WikiArticle[]>([])
const filter = ref('')
const activeSlug = ref('')
const activeTitle = ref('')
const activeContent = ref('')

const filtered = computed(() => {
  const needle = filter.value.trim().toLowerCase()
  if (!needle) return articles.value
  return articles.value.filter(
    article =>
      article.title.toLowerCase().includes(needle) ||
      article.summary.toLowerCase().includes(needle) ||
      article.slug.toLowerCase().includes(needle),
  )
})

async function load(): Promise<void> {
  try {
    const payload = await props.requestRpc('library.wiki.list', {})
    articles.value = Array.isArray(payload.articles) ? (payload.articles as WikiArticle[]) : []
  } catch {
    articles.value = []
  }
}

async function open(slug: string): Promise<void> {
  try {
    const payload = await props.requestRpc('library.wiki.read', { slug })
    activeTitle.value = String(payload.title || slug)
    activeContent.value = String(payload.content || '')
    activeSlug.value = slug
  } catch {
    activeContent.value = t('读取失败')
    activeSlug.value = slug
  }
}

onMounted(load)
</script>

<style scoped>
.wiki-view { display: grid; gap: 12px; align-content: start; }
.wiki-head { display: grid; gap: 6px; }
.wiki-sub { margin: 0; font-size: 13px; opacity: 0.7; }
.wiki-filter { padding: 8px 10px; border-radius: var(--radius); border: 1px solid color-mix(in srgb, currentColor 20%, transparent); background: transparent; color: inherit; }
.wiki-list { display: grid; gap: 6px; }
.wiki-row { display: grid; gap: 2px; text-align: left; padding: 10px 12px; border-radius: var(--radius); border: 1px solid color-mix(in srgb, currentColor 14%, transparent); background: transparent; color: inherit; cursor: pointer; }
.wiki-row:hover { border-color: color-mix(in srgb, currentColor 35%, transparent); }
.wiki-summary { font-size: 12px; opacity: 0.7; }
.wiki-empty { opacity: 0.6; }
.wiki-article { display: grid; gap: 10px; }
.wiki-article-head { display: flex; align-items: baseline; gap: 12px; }
</style>
