// user:“wiki中的各类链接点击后无法跳转与返回 / 左侧以窄栏显示文件层级 /
// 目录与进度悬浮在右侧，点击自动跳转”+(Wiki 要能按层级浏览、文内链接可跳转、
// 可以返回，并提供右侧目录与阅读进度)。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import WikiView from '../src/components/WikiView.vue'
import {
  resolveWikiHref,
  wikiHeadingId,
  wikiScrollProgress,
} from '../src/components/wikiNavigation'

/** 只负责把现成 HTML 塞进 .markdown-body 的渲染替身；真实 marked 渲染另有测试。 */
const InlineMarkdown = defineComponent({
  props: { content: { type: String, default: '' } },
  template: '<div class="markdown-body" v-html="content" />',
})

const ARTICLES = [
  { slug: 'articles/welcome', title: 'Sunday 是什么', summary: '总览', section: 'articles', size: 10 },
  { slug: 'articles/library', title: '资料库', summary: '资料与成果', section: 'articles', size: 10 },
  { slug: 'articles/mcp', title: 'MCP', summary: '外部工具', section: 'articles', size: 10 },
]
const NAVIGATION = {
  index: 'README',
  groups: [
    { id: 'group-0', title: '一、开始使用', articles: ['articles/welcome'] },
    { id: 'group-1', title: '九、技能、记忆与外部工具', articles: ['articles/library', 'articles/mcp'] },
  ],
}
const CONTENT: Record<string, string> = {
  README: '<h1>Sunday Wiki 目录</h1><h2>一、开始使用</h2><p><a href="articles/library.md">资料库</a></p>',
  'articles/library': [
    '<h1>资料库</h1>',
    '<h2>安装</h2>',
    '<p><a href="#%E5%AE%89%E8%A3%85">跳到安装</a></p>',
    '<p><a href="split-pane.md">分屏</a></p>',
    '<p><a href="../../core/src/lamtools_core/app/x.py">实现</a></p>',
    '<h3>小节</h3>',
  ].join(''),
  'articles/split-pane': '<h1>分屏</h1><p>正文</p>',
}
const TITLES: Record<string, string> = {
  README: 'Sunday Wiki 目录',
  'articles/library': '资料库',
  'articles/split-pane': '分屏',
}

function mountWiki(content: Record<string, string> = CONTENT) {
  const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    if (method === 'library.wiki.list') return { articles: ARTICLES, navigation: NAVIGATION }
    if (method === 'library.wiki.read') {
      const slug = String(params?.slug ?? '')
      if (!(slug in content)) throw new Error(`missing ${slug}`)
      return { slug, title: TITLES[slug] ?? slug, content: content[slug] }
    }
    return {}
  })
  const wrapper = mount(WikiView, {
    props: { requestRpc: rpc },
    global: { stubs: { MarkdownRenderer: InlineMarkdown } },
    attachTo: document.body,
  })
  return { wrapper, rpc }
}

async function settle(): Promise<void> {
  await flushPromises()
  await new Promise(resolve => setTimeout(resolve, 0))
  await flushPromises()
}

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('wiki link resolution', () => {
  it('resolves sibling markdown links from the current article', () => {
    expect(resolveWikiHref('split-pane.md', 'articles/library')).toEqual({ slug: 'articles/split-pane', hash: '' })
    expect(resolveWikiHref('../articles/welcome.md#概述', 'articles/library')).toEqual({ slug: 'articles/welcome', hash: '概述' })
    expect(resolveWikiHref('articles/welcome.md', 'README')).toEqual({ slug: 'articles/welcome', hash: '' })
    expect(resolveWikiHref('./mcp.md', 'articles/library')).toEqual({ slug: 'articles/mcp', hash: '' })
  })

  it('decodes in-article anchors', () => {
    expect(resolveWikiHref('#%E5%AE%89%E8%A3%85', 'articles/library')).toEqual({ slug: 'articles/library', hash: '安装' })
    expect(resolveWikiHref('#安装', 'articles/library')).toEqual({ slug: 'articles/library', hash: '安装' })
  })

  it('ignores external urls and links that escape the wiki', () => {
    expect(resolveWikiHref('https://example.test/a.md', 'articles/library')).toBeNull()
    expect(resolveWikiHref('../../core/src/app.py', 'articles/library')).toBeNull()
    expect(resolveWikiHref('../../../outside.md', 'README')).toBeNull()
    expect(resolveWikiHref('mailto:a@b.test', 'README')).toBeNull()
  })
})

describe('wiki heading ids and progress', () => {
  it('builds stable heading ids from heading text', () => {
    expect(wikiHeadingId('安装、启动与版本')).toBe('安装启动与版本')
    expect(wikiHeadingId('第一步：读规则和现状')).toBe('第一步读规则和现状')
    expect(wikiHeadingId('  Hello   World ')).toBe('hello-world')
    expect(wikiHeadingId('A/B: C')).toBe('ab-c')
  })

  it('maps scroll position to a 0–1 reading progress', () => {
    expect(wikiScrollProgress(0, 500, 1500)).toBe(0)
    expect(wikiScrollProgress(500, 500, 1500)).toBe(0.5)
    expect(wikiScrollProgress(1200, 500, 1500)).toBe(1)
    expect(wikiScrollProgress(0, 500, 500)).toBe(0)
    expect(wikiScrollProgress(0, 500, 400)).toBe(0)
  })
})

describe('WikiView chrome', () => {
  it('shows the README outline as a narrow two-level rail and filters it', async () => {
    const { wrapper } = mountWiki()
    await settle()

    const groups = wrapper.findAll('[data-wiki-group]')
    expect(groups).toHaveLength(2)
    expect(groups[0].text()).toContain('一、开始使用')

    const filter = wrapper.get('[data-wiki-filter]')
    await filter.setValue('mcp')
    await settle()
    expect(wrapper.findAll('[data-wiki-group]')).toHaveLength(1)
    expect(wrapper.findAll('[data-wiki-article-item]')).toHaveLength(1)
    expect(wrapper.get('[data-wiki-article-item]').text()).toContain('MCP')

    await filter.setValue('不存在的文档')
    await settle()
    expect(wrapper.text()).toContain('没有匹配的文档')
  })

  it('opens the index and navigates through markdown links and back', async () => {
    const { wrapper, rpc } = mountWiki()
    await settle()
    expect(rpc).toHaveBeenCalledWith('library.wiki.read', { slug: 'README' })
    expect(wrapper.get('[data-wiki-active-title]').text()).toContain('Sunday Wiki 目录')

    await wrapper.get('a[href="articles/library.md"]').trigger('click')
    await settle()
    expect(rpc).toHaveBeenCalledWith('library.wiki.read', { slug: 'articles/library' })
    expect(wrapper.get('[data-wiki-article-item].active').text()).toContain('资料库')
    expect(wrapper.get('[data-wiki-crumb]').text()).toContain('资料库')

    await wrapper.get('a[href="split-pane.md"]').trigger('click')
    await settle()
    expect(wrapper.text()).toContain('正文')

    await wrapper.get('[data-wiki-back]').trigger('click')
    await settle()
    expect(wrapper.get('[data-wiki-active-title]').text()).toContain('资料库')

    await wrapper.get('[data-wiki-back]').trigger('click')
    await settle()
    expect(wrapper.get('[data-wiki-active-title]').text()).toContain('Sunday Wiki 目录')
    expect(wrapper.find('[data-wiki-back]').exists()).toBe(false)
    expect((wrapper.vm as unknown as { handleBack: () => boolean }).handleBack()).toBe(false)
  })

  it('assigns heading ids and scrolls to in-article anchors', async () => {
    const { wrapper } = mountWiki()
    await settle()
    await wrapper.get('a[href="articles/library.md"]').trigger('click')
    await settle()

    const heading = wrapper.get('[data-wiki-heading="安装"]')
    expect(heading.element.tagName).toBe('H2')
    const scroll = vi.fn()
    ;(heading.element as HTMLElement).scrollIntoView = scroll

    await wrapper.get('a[href="#%E5%AE%89%E8%A3%85"]').trigger('click')
    expect(scroll).toHaveBeenCalled()

    // 源码路径不在 wiki 里：拦下导航，但不要整页跳走。
    const sourceLink = wrapper.get('a[href="../../core/src/lamtools_core/app/x.py"]')
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    sourceLink.element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(wrapper.get('[data-wiki-active-title]').text()).toContain('资料库')
  })

  it('renders the floating outline and reports reading progress', async () => {
    const { wrapper } = mountWiki()
    await settle()
    await wrapper.get('a[href="articles/library.md"]').trigger('click')
    await settle()

    const items = wrapper.findAll('[data-wiki-toc-item]')
    expect(items.map(item => item.text())).toEqual(['安装', '小节'])

    const scroller = wrapper.get('[data-wiki-scroll]').element as HTMLElement
    Object.defineProperty(scroller, 'scrollHeight', { configurable: true, value: 1500 })
    Object.defineProperty(scroller, 'clientHeight', { configurable: true, value: 500 })
    scroller.scrollTop = 500
    scroller.dispatchEvent(new Event('scroll'))
    await settle()
    expect(wrapper.get('[data-wiki-progress]').text()).toContain('50%')

    const target = wrapper.get('[data-wiki-heading="小节"]').element as HTMLElement
    const scroll = vi.fn()
    target.scrollIntoView = scroll
    await items[1].trigger('click')
    expect(scroll).toHaveBeenCalled()
    expect(items[1].classes()).toContain('active')
  })

  // 用真实 wiki 文件 + 真实 MarkdownRenderer 走一遍：README 的链接进文章，
  // 文章自带的「目录」锚点（#第一步读规则和现状 这种省略标点的写法）能落到标题。
  it('navigates the bundled wiki with the real markdown renderer', async () => {
    const wikiDir = resolve(process.cwd(), '../../wiki')
    const readArticle = (slug: string) => readFileSync(resolve(wikiDir, `${slug}.md`), 'utf8')
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'library.wiki.list') {
        return {
          articles: [
            { slug: 'articles/plugin-cases', title: '插件案例', summary: '', section: 'articles', size: 1 },
          ],
          navigation: { index: 'README', groups: [{ id: 'group-0', title: '十、插件', articles: ['articles/plugin-cases'] }] },
        }
      }
      if (method === 'library.wiki.read') {
        const slug = String(params?.slug ?? '')
        return { slug, title: slug === 'README' ? 'Sunday Wiki 目录' : '插件案例', content: readArticle(slug) }
      }
      return {}
    })
    const wrapper = mount(WikiView, { props: { requestRpc: rpc } })
    try {
      await settle()

      await wrapper.get('a[href="articles/plugin-cases.md"]').trigger('click')
      await settle()

      const heading = wrapper.get('[data-wiki-heading="案例授权分层评论与私信类能力"]')
      expect(heading.element.tagName).toBe('H2')
      const scroll = vi.fn()
      ;(heading.element as HTMLElement).scrollIntoView = scroll

      await wrapper.get(`[data-wiki-article] a[href="#${encodeURIComponent('案例授权分层评论与私信类能力')}"]`).trigger('click')
      expect(scroll).toHaveBeenCalled()
      expect(wrapper.findAll('[data-wiki-toc-item]').length).toBeGreaterThan(3)
    } finally {
      wrapper.unmount()
    }
  })
})
