import { describe, expect, it, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'
import {
  MARKDOWN_CACHE_MAX_CHARS,
  MARKDOWN_CACHE_MAX_ENTRIES,
  getCachedMarkdown,
  markdownCacheStatsForTests,
  resetMarkdownCacheForTests,
  setCachedMarkdown,
} from '../src/components/markdownRenderCache'

function emptyEntry() {
  return { html: '', blocks: [], seq: 0, inlinePlots: [], inlinePlotSeq: 0 }
}

describe('markdown render cache (module-level LRU)', () => {
  beforeEach(() => resetMarkdownCacheForTests())

  it('renews recency on hit so touched entries outlive untouched ones', () => {
    // 填满容量。
    for (let index = 0; index < MARKDOWN_CACHE_MAX_ENTRIES; index += 1) {
      setCachedMarkdown(`k-${index}`, emptyEntry())
    }
    // 触碰最旧的一条，再塞入新条目：被触碰的存活，未被触碰的最旧者出局。
    expect(getCachedMarkdown('k-0')).toBeDefined()
    setCachedMarkdown('k-new', emptyEntry())
    expect(getCachedMarkdown('k-0')).toBeDefined()
    expect(getCachedMarkdown('k-1')).toBeUndefined()
  })

  it('evicts by entry cap', () => {
    for (let index = 0; index < MARKDOWN_CACHE_MAX_ENTRIES + 5; index += 1) {
      setCachedMarkdown(`key-${index}`, emptyEntry())
    }
    expect(markdownCacheStatsForTests().entries).toBe(MARKDOWN_CACHE_MAX_ENTRIES)
    expect(getCachedMarkdown('key-0')).toBeUndefined()
    expect(getCachedMarkdown(`key-${MARKDOWN_CACHE_MAX_ENTRIES + 4}`)).toBeDefined()
  })

  it('evicts by total cached chars and bypasses oversized entries', () => {
    const half = Math.floor(MARKDOWN_CACHE_MAX_CHARS * 0.6)
    setCachedMarkdown('x'.repeat(half), emptyEntry())
    setCachedMarkdown('y'.repeat(half), emptyEntry())
    const stats = markdownCacheStatsForTests()
    expect(stats.chars).toBeLessThanOrEqual(MARKDOWN_CACHE_MAX_CHARS)
    expect(getCachedMarkdown('x'.repeat(half))).toBeUndefined()
    expect(getCachedMarkdown('y'.repeat(half))).toBeDefined()

    // 超长单条不缓存。
    setCachedMarkdown('z'.repeat(MARKDOWN_CACHE_MAX_CHARS + 1), emptyEntry())
    expect(getCachedMarkdown('z'.repeat(MARKDOWN_CACHE_MAX_CHARS + 1))).toBeUndefined()
  })

  it('shares cached entries across renderer instances so revisited sessions skip re-parsing', async () => {
    const content = '# Shared\n\nSame **content** twice.'
    const first = mount(MarkdownRenderer, { props: { content } })
    await nextTick()
    const htmlBefore = first.find('.markdown-renderer__content').html()
    first.unmount()
    const entriesBefore = markdownCacheStatsForTests().entries
    expect(entriesBefore).toBeGreaterThan(0)

    // 卸载后重挂（模拟回访会话）：同内容命中共享缓存，条目数不增。
    const second = mount(MarkdownRenderer, { props: { content } })
    await nextTick()
    expect(second.find('.markdown-renderer__content').html()).toBe(htmlBefore)
    expect(markdownCacheStatsForTests().entries).toBe(entriesBefore)
    second.unmount()
  })
})
