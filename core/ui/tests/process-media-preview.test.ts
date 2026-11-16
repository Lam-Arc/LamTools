import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import ProcessMediaPreview from '../src/components/process/ProcessMediaPreview.vue'
import ProcessResultPills from '../src/components/process/ProcessResultPills.vue'
import ProcessKvPill from '../src/components/process/ProcessKvPill.vue'

// user:“单文件：圆角矩形缩略图，高度固定 80~120px（取 96px），宽度按原图比例自适应，最大不超过容器宽度 60%”
// +(验收：400×300 的图在 96px 高下算出 128px 宽，并且始终带 60% 封顶。)
// user:“多文件……超过 5 张时末位显示 +N 遮罩”+(验收：6 张只画 5 格，末格盖 +1。)
// user:“文件损坏或加载超时（3s）平滑降级成对应格式的文件类型徽章卡片，绝不出现破图图标”
// +(验收：报错/超时后 DOM 里没有 <img>，只剩类型徽章卡片。)

function imageFile(index: number, extra: Record<string, unknown> = {}) {
  return {
    path: `.lam/artifacts/img-${index}.png`,
    name: `img-${index}.png`,
    mime: 'image/png',
    url: `asset://localhost/img-${index}.png`,
    ...extra,
  }
}

afterEach(() => {
  vi.useRealTimers()
  delete (window as { __LAMTOOLS_OPEN_URL__?: unknown }).__LAMTOOLS_OPEN_URL__
})

describe('ProcessMediaPreview', () => {
  it('单文件按原图比例算宽度，并封顶容器 60%', () => {
    const wrapper = mount(ProcessMediaPreview, {
      props: { files: [imageFile(1, { width: 400, height: 300 })] },
    })
    const cell = wrapper.get('.process-media__cell')
    const style = cell.attributes('style') || ''
    expect(style).toContain('width: 128px')
    expect(style).toContain('max-width: 60%')
    expect(style).toContain('height: 96px')
    expect(wrapper.get('img').attributes('src')).toBe('asset://localhost/img-1.png')
  })

  it('没有宽高时不硬算宽度，只保留 60% 封顶', () => {
    const wrapper = mount(ProcessMediaPreview, { props: { files: [imageFile(2)] } })
    const style = wrapper.get('.process-media__cell').attributes('style') || ''
    expect(style).toContain('max-width: 60%')
    // 只断言没有独立的 width 声明（max-width 里也含 "width:"，所以按声明边界匹配）
    expect(style).not.toMatch(/(^|;\s*)width:/)
  })

  it('mediaHeight 覆盖默认 96px', () => {
    const wrapper = mount(ProcessMediaPreview, {
      props: { files: [imageFile(3, { width: 100, height: 100 })], mediaHeight: 80 },
    })
    const style = wrapper.get('.process-media__cell').attributes('style') || ''
    expect(style).toContain('height: 80px')
    expect(style).toContain('width: 80px')
  })

  it('多文件超过 5 张时末位出现 +N 遮罩', () => {
    const files = Array.from({ length: 6 }, (_, index) => imageFile(index))
    const wrapper = mount(ProcessMediaPreview, { props: { files } })
    const cells = wrapper.findAll('.process-media__cell')
    expect(cells.length).toBe(5)
    expect(cells[4]!.find('.process-media__more').text()).toBe('+1')
    expect(cells[0]!.find('.process-media__more').exists()).toBe(false)
  })

  it('恰好 5 张时不出现 +N 遮罩', () => {
    const files = Array.from({ length: 5 }, (_, index) => imageFile(index))
    const wrapper = mount(ProcessMediaPreview, { props: { files } })
    expect(wrapper.findAll('.process-media__cell').length).toBe(5)
    expect(wrapper.find('.process-media__more').exists()).toBe(false)
  })

  it('加载失败降级成文件类型徽章，且不再留 <img>', async () => {
    const wrapper = mount(ProcessMediaPreview, { props: { files: [imageFile(1)] } })
    expect(wrapper.find('img').exists()).toBe(true)
    await wrapper.get('img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.process-media__fallback').exists()).toBe(true)
    expect(wrapper.get('.process-media__cell').attributes('data-media-kind')).toBe('image')
  })

  it('加载超时 3s 同样降级成徽章', async () => {
    vi.useFakeTimers()
    const wrapper = mount(ProcessMediaPreview, { props: { files: [imageFile(1)] } })
    expect(wrapper.find('img').exists()).toBe(true)
    vi.advanceTimersByTime(3000)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.process-media__fallback').exists()).toBe(true)
  })

  it('error 标记的文件直接出徽章，不挂 <img>', () => {
    const wrapper = mount(ProcessMediaPreview, { props: { files: [imageFile(1, { error: true })] } })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.process-media__fallback').exists()).toBe(true)
  })

  it('没有 url 的图片不硬试，直接出徽章', () => {
    const wrapper = mount(ProcessMediaPreview, {
      props: { files: [{ path: '.lam/artifacts/a.png', name: 'a.png', mime: 'image/png' }] },
    })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.process-media__fallback').exists()).toBe(true)
  })

  it('音频走波形占位、视频走 <video>，都不出 <img>', () => {
    const wrapper = mount(ProcessMediaPreview, {
      props: {
        files: [
          { path: '.lam/artifacts/voice.mp3', name: 'voice.mp3', mime: 'audio/mpeg' },
          { path: '.lam/artifacts/clip.mp4', name: 'clip.mp4', mime: 'video/mp4', url: 'asset://localhost/clip.mp4' },
        ],
      },
    })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.process-media__wave').exists()).toBe(true)
    expect(wrapper.find('video').exists()).toBe(true)
  })

  // user:“ProcessMediaPreview 支持 pdf 类型：无缩略图时显示 PDF 徽章卡片而不是空框”
  // +(验收：PDF 没给首页缩略图时不出现空框，也不出现 <img>，而是类型徽章卡片。)
  it('PDF 无缩略图时出徽章卡片，不是空框', () => {
    const wrapper = mount(ProcessMediaPreview, {
      props: { files: [{ path: '.lam/artifacts/report.pdf', name: 'report.pdf', mime: 'application/pdf', size: 204800 }] },
    })
    const cell = wrapper.get('.process-media__cell')
    expect(cell.attributes('data-media-kind')).toBe('document')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.process-media__fallback').exists()).toBe(true)
    expect(wrapper.get('.process-media__fallback-name').text()).toBe('report.pdf')
    expect(wrapper.text()).toContain('200 KB')
  })

  it('PDF 给了首页缩略图就画图并标 PDF', () => {
    const wrapper = mount(ProcessMediaPreview, {
      props: {
        files: [{
          path: '.lam/artifacts/report.pdf',
          name: 'report.pdf',
          mime: 'application/pdf',
          thumb: 'asset://localhost/report-page-1.png',
        }],
      },
    })
    expect(wrapper.get('img').attributes('src')).toBe('asset://localhost/report-page-1.png')
    expect(wrapper.get('.process-media__doc-chip').text()).toBe('PDF')
    expect(wrapper.find('.process-media__fallback').exists()).toBe(false)
  })

  // user:“音视频 mp4/webm……首帧缩略图或波形图占位”+(给了首帧图就画图，不再挂 <video> 拉解码器)。
  it('视频给了首帧缩略图就画图并叠播放标记', () => {
    const wrapper = mount(ProcessMediaPreview, {
      props: {
        files: [{
          path: '.lam/artifacts/clip.mp4',
          name: 'clip.mp4',
          mime: 'video/mp4',
          thumb: 'asset://localhost/clip-first-frame.png',
        }],
      },
    })
    expect(wrapper.find('video').exists()).toBe(false)
    expect(wrapper.get('.process-media__poster img').attributes('src')).toBe('asset://localhost/clip-first-frame.png')
    expect(wrapper.find('.process-media__play').exists()).toBe(true)
  })

  it('点缩略图只抛 preview 事件（灯箱由外部承接）', async () => {
    const file = imageFile(1)
    const wrapper = mount(ProcessMediaPreview, { props: { files: [file] } })
    await wrapper.get('.process-media__cell').trigger('click')
    expect(wrapper.emitted('preview')?.[0]).toEqual([file])
    // 组件自己不画遮罩层
    expect(wrapper.find('.process-media__lightbox').exists()).toBe(false)
  })

  it('空列表不渲染任何内容', () => {
    const wrapper = mount(ProcessMediaPreview, { props: { files: [] } })
    expect(wrapper.find('.process-media').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })
})

describe('ProcessResultPills', () => {
  it('标题单行截断并带完整 title 属性', () => {
    const title = '一个特别长的搜索结果标题用来验证胶囊里的单行截断行为是否正确生效'
    const wrapper = mount(ProcessResultPills, {
      props: { results: [{ title, url: 'https://example.com/a' }] },
    })
    const pill = wrapper.get('.process-pills__pill')
    expect(pill.attributes('title')).toBe(title)
    expect(pill.get('.process-pills__title').text()).toBe(title)
  })

  it('点击走 openUrl 桥打开原文，不裸调 window.open', async () => {
    const bridge = vi.fn().mockResolvedValue(true)
    ;(window as { __LAMTOOLS_OPEN_URL__?: unknown }).__LAMTOOLS_OPEN_URL__ = bridge
    const windowOpen = vi.spyOn(window, 'open').mockImplementation(() => null)
    const result = { title: '结果标题', url: 'https://example.com/a' }
    const wrapper = mount(ProcessResultPills, { props: { results: [result] } })
    await wrapper.get('.process-pills__pill').trigger('click')
    await flushPromises()
    expect(bridge).toHaveBeenCalledWith('https://example.com/a')
    expect(windowOpen).not.toHaveBeenCalled()
    expect(wrapper.emitted('open')?.[0]).toEqual([result])
    windowOpen.mockRestore()
  })

  it('favicon 加载失败降级成首字母圆点', async () => {
    const wrapper = mount(ProcessResultPills, {
      props: { results: [{ title: 'Sunday 文档', favicon: 'https://example.com/f.ico' }] },
    })
    expect(wrapper.find('.process-pills__favicon img').exists()).toBe(true)
    await wrapper.get('.process-pills__favicon img').trigger('error')
    expect(wrapper.find('.process-pills__favicon img').exists()).toBe(false)
    expect(wrapper.get('.process-pills__initial').text()).toBe('S')
  })

  it('空结果不渲染', () => {
    const wrapper = mount(ProcessResultPills, { props: { results: [] } })
    expect(wrapper.find('.process-pills').exists()).toBe(false)
  })
})

describe('ProcessKvPill', () => {
  const entries = ['query', 'model', 'topK', 'scope', 'lang'].map((key) => ({ key, value: `${key}-value` }))

  it('超过 3 个键值折叠成 +N，展开后可看全部', async () => {
    const wrapper = mount(ProcessKvPill, { props: { entries } })
    expect(wrapper.findAll('.process-kv__entry').length).toBe(3)
    const more = wrapper.get('.process-kv__more')
    expect(more.text()).toBe('+2')
    await more.trigger('click')
    expect(wrapper.findAll('.process-kv__entry').length).toBe(5)
    expect(wrapper.get('.process-kv__more').text()).toBe('收起')
  })

  it('不超过 3 个键值时不出现 +N', () => {
    const wrapper = mount(ProcessKvPill, { props: { entries: entries.slice(0, 2) } })
    expect(wrapper.find('.process-kv__more').exists()).toBe(false)
  })

  it('状态徽章带语义色类名并显示耗时', () => {
    const wrapper = mount(ProcessKvPill, {
      props: { entries: entries.slice(0, 1), status: 'success', durationMs: 1234 },
    })
    const badge = wrapper.get('.process-kv__status')
    expect(badge.classes()).toContain('process-kv__status--success')
    expect(badge.text()).toContain('成功')
    expect(badge.text()).toContain('1.2s')
  })

  it('毫秒级耗时直接显示 ms', () => {
    const wrapper = mount(ProcessKvPill, {
      props: { entries: entries.slice(0, 1), status: 'running', durationMs: 87 },
    })
    expect(wrapper.get('.process-kv__status').text()).toContain('87ms')
    expect(wrapper.get('.process-kv__status').classes()).toContain('process-kv__status--running')
  })

  it('键值都不给也不渲染', () => {
    const wrapper = mount(ProcessKvPill, { props: { entries: [] } })
    expect(wrapper.find('.process-kv').exists()).toBe(false)
  })

  // user:“ProcessKvPill 的 durationMs 支持到分钟级（65s、2m05s），不要出现 125.3s 这种”
  // +(验收：跨分钟进位成 XmSSs，秒补零；一分钟以内仍是秒。)
  it('耗时跨分钟进位成分钟级，不出现 125.3s', () => {
    const badgeOf = (durationMs: number) => mount(ProcessKvPill, {
      props: { entries: entries.slice(0, 1), status: 'success', durationMs },
    }).get('.process-kv__status').text()

    expect(badgeOf(65_000)).toContain('1m05s')
    expect(badgeOf(125_300)).toContain('2m05s')
    expect(badgeOf(125_300)).not.toContain('125.3s')
    expect(badgeOf(61_000)).toContain('1m01s')
    expect(badgeOf(600_000)).toContain('10m00s')
    expect(badgeOf(59_400)).toContain('59.4s')
  })
})

// user:“在 Gallery.vue 里为三个组件各加一组展品，遵循该文件既有的展品结构”+
// (验收：展厅里搜到就能直接渲染生产组件，且展品本身覆盖 PRD 要求的各态。)
describe('设计系统展厅展品', () => {
  async function openSpecimen(name: string) {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue(name)
    await flushPromises()
    return wrapper
  }

  it('ProcessMediaPreview 展品覆盖单图、多图、+N、降级与占位', async () => {
    const wrapper = await openSpecimen('ProcessMediaPreview')
    // 8 组展品：16:9、1:1、3 张、7 张、坏图、音频、视频、PDF
    expect(wrapper.findAll('.process-media').length).toBe(8)
    // 7 张只画 5 格，末格盖 +2
    expect(wrapper.find('.process-media__more').text()).toBe('+2')
    // 坏图与 PDF 无缩略图都落到徽章卡片
    expect(wrapper.findAll('.process-media__fallback').length).toBeGreaterThanOrEqual(2)
    expect(wrapper.find('.process-media__wave').exists()).toBe(true)
    expect(wrapper.find('.process-media__play').exists()).toBe(true)
    await wrapper.get('.process-media__cell').trigger('click')
    expect(wrapper.get('[data-gallery-media-preview-result]').text()).toContain('已请求预览')
    wrapper.unmount()
  })

  it('ProcessResultPills 展品有 5 条结果，缺站标的两条走首字母', async () => {
    const wrapper = await openSpecimen('ProcessResultPills')
    expect(wrapper.findAll('.process-pills__pill').length).toBe(5)
    expect(wrapper.findAll('.process-pills__initial').length).toBe(2)
    wrapper.unmount()
  })

  it('ProcessKvPill 展品同时展示折叠态与分钟级耗时', async () => {
    const wrapper = await openSpecimen('ProcessKvPill')
    expect(wrapper.findAll('.process-kv').length).toBe(2)
    expect(wrapper.get('.process-kv__more').text()).toBe('+2')
    expect(wrapper.get('.process-kv__status').text()).toContain('2m05s')
    wrapper.unmount()
  })
})

describe('process-media.css 契约变量', () => {
  const css = readFileSync(resolve(import.meta.dirname, '../src/styles/process-media.css'), 'utf8')

  it('六个契约变量都带兜底默认值', () => {
    expect(css).toContain('var(--ms-proc-radius-sm, 8px)')
    expect(css).toContain('var(--ms-proc-radius-lg, 12px)')
    expect(css).toContain('var(--ms-proc-border-color,')
    expect(css).toContain('var(--ms-proc-fill-color,')
    expect(css).toContain('var(--ms-proc-fill-alpha, 0)')
    expect(css).toContain('var(--ms-proc-blur, 0px)')
    expect(css).toContain('var(--ms-proc-body-font-size, 12px)')
  })

  it('不出现字面量色值', () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
