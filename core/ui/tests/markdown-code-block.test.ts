import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

// Mermaid is lazy-loaded only when a ```mermaid block exists; stub the module
// so jsdom never needs to run the real (browser-oriented) renderer.
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg></svg>' }),
  },
}))

function stubClipboard(): ReturnType<typeof vi.fn> {
  const writeText = vi.fn().mockResolvedValue(undefined)
  try {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  } catch {
    // Non-configurable in this jsdom — replace the whole global instead.
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
  }
  return writeText
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  try {
    delete (navigator as { clipboard?: unknown }).clipboard
  } catch {
    // ignore — clipboard was never stubbed
  }
  vi.restoreAllMocks()
})

describe('MarkdownRenderer code blocks', () => {
  it('renders ```markdown blocks as nested documents with a copy button carrying the raw source', async () => {
    const source = '# 标题\n\n- 一\n- 二'
    const wrapper = mount(MarkdownRenderer, { props: { content: `\`\`\`markdown\n${source}\n\`\`\`` } })
    await wrapper.vm.$nextTick()

    const block = wrapper.find('.code-block')
    expect(block.exists()).toBe(true)
    expect(block.find('.nested-markdown h1').text()).toBe('标题')
    expect(block.find('.nested-markdown li').text()).toBe('一')
    expect(block.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('keeps the copy source lossless for `<`, `&`, `"`, `-->` and `</script>`', async () => {
    const source = 'print("<a>&</a>")\n// --> done\nconst s = "</script>"'
    const wrapper = mount(MarkdownRenderer, { props: { content: `\`\`\`py\n${source}\n\`\`\`` } })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.code-block pre code').text()).toBe(source)
    expect(wrapper.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('wraps ```mermaid blocks in a code block with a copy button', async () => {
    const source = 'graph TD\n  A-->B'
    const wrapper = mount(MarkdownRenderer, { props: { content: `\`\`\`mermaid\n${source}\n\`\`\`` } })
    await wrapper.vm.$nextTick()
    await flushPromises()

    const block = wrapper.find('.code-block')
    expect(block.exists()).toBe(true)
    // The placeholder is processed (replaced by the diagram or the error fallback).
    expect(block.find('.mermaid-placeholder').exists()).toBe(false)
    expect(block.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('streaming code blocks carry the same copy button structure', async () => {
    const source = 'print(1)'
    const wrapper = mount(MarkdownRenderer, {
      props: { content: `\`\`\`py\n${source}\n\`\`\``, streaming: true },
    })
    await wrapper.vm.$nextTick()

    const block = wrapper.find('.code-block')
    expect(block.find('pre code').text()).toBe(source)
    expect(block.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('copies the raw source on click and shows the copied state for 1400ms', async () => {
    vi.useFakeTimers()
    const writeText = stubClipboard()
    const source = 'x = 1'
    const wrapper = mount(MarkdownRenderer, { props: { content: `\`\`\`py\n${source}\n\`\`\`` } })
    await wrapper.vm.$nextTick()

    const button = wrapper.find('.code-copy')
    await button.trigger('click')
    expect(writeText).toHaveBeenCalledWith(source)
    expect(button.attributes('data-copied')).toBeDefined()

    vi.advanceTimersByTime(1400)
    expect(button.attributes('data-copied')).toBeUndefined()
    wrapper.unmount()
  })
})

describe('MarkdownRenderer source-backed images', () => {
  it('allows only HTTPS remote images and applies privacy and loading attributes', async () => {
    const wrapper = mount(MarkdownRenderer, { props: {
      content: [
        '![Newton portrait](https://images.example.test/newton.jpg)',
        '![Blocked](http://images.example.test/insecure.jpg)',
      ].join('\n\n'),
      autoPlotMath: true,
    } })
    await wrapper.vm.$nextTick()

    const images = wrapper.findAll('img')
    expect(images).toHaveLength(2)
    expect(images[0].attributes()).toMatchObject({
      src: 'https://images.example.test/newton.jpg',
      loading: 'lazy',
      decoding: 'async',
      referrerpolicy: 'no-referrer',
      alt: 'Newton portrait',
    })
    expect(images[1].attributes('src')).toBeUndefined()
    expect(images[1].attributes('data-image-blocked')).toBe('insecure-source')
    wrapper.unmount()
  })

  it('renders sanitized fenced SVG diagrams only when Study enables media rendering', async () => {
    const source = [
      '<svg viewBox="0 0 100 50">',
      '<title>KVL loop</title>',
      '<style>text{font:13px sans-serif;fill:#111}.w{stroke:#111;stroke-width:2;fill:none}</style>',
      '<defs><marker id="ah" markerWidth="8" markerHeight="8" refX="6" refY="3"><path d="M0 0L6 3L0 6z"/></marker></defs>',
      '<path class="w" d="M5 25H95" marker-end="url(#ah)"/><text x="5" y="15">R1</text>',
      '</svg>',
    ].join('')
    const outsideStudy = mount(MarkdownRenderer, { props: { content: `\`\`\`svg\n${source}\n\`\`\`` } })
    await outsideStudy.vm.$nextTick()
    expect(outsideStudy.find('.study-inline-svg').exists()).toBe(false)
    expect(outsideStudy.find('pre code').text()).toBe(source)
    outsideStudy.unmount()

    const inStudy = mount(MarkdownRenderer, {
      props: { content: `\`\`\`svg\n${source}\n\`\`\``, autoPlotMath: true },
    })
    await inStudy.vm.$nextTick()
    expect(inStudy.find('.study-inline-svg').exists()).toBe(true)
    expect(inStudy.find('.study-inline-svg svg').attributes()).toMatchObject({
      role: 'img',
      'aria-label': 'KVL loop',
    })
    expect(inStudy.find('pre code').exists()).toBe(false)
    expect(inStudy.find('path.w').attributes()).toMatchObject({ stroke: 'currentColor', 'stroke-width': '2', fill: 'none' })
    expect(inStudy.find('marker#ah').exists()).toBe(true)
    expect(inStudy.find('path.w').attributes('marker-end')).toBe('url(#ah)')
    expect(inStudy.find('text').attributes()).toMatchObject({
      'font-size': '13px',
      'font-family': 'sans-serif',
      fill: 'currentColor',
    })
    expect(inStudy.find('style').exists()).toBe(false)
    inStudy.unmount()
  })

  it('renders the complete KVL diagram from the saved Study reply with theme-visible paint', async () => {
    const source = [
      '<svg xmlns="http://www.w3.org/2000/svg" width="520" height="300" viewBox="0 0 520 300">',
      '<style>text{font:13px sans-serif;fill:#111}.w{stroke:#111;stroke-width:2;fill:none}</style>',
      '<defs><marker id="ah" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0 0L6 3L0 6z" fill="#111"/></marker></defs>',
      '<g class="w"><path d="M60 50H110"/><path d="M190 50H400"/><rect x="110" y="42" width="80" height="16"/><path d="M60 50V110"/><path d="M60 170V250"/><circle cx="60" cy="140" r="30"/><path d="M60 250H400"/><path d="M300 50V105"/><rect x="292" y="105" width="16" height="80"/><path d="M300 185V250"/><path d="M400 50V105"/><rect x="392" y="105" width="16" height="80"/><path d="M400 185V250"/></g>',
      '<path class="w" d="M215 50H255" marker-end="url(#ah)"/><path class="w" d="M300 62V98" marker-end="url(#ah)"/><path class="w" d="M400 62V98" marker-end="url(#ah)"/>',
      '<path class="w" stroke-dasharray="6 5" d="M340 50V250"/><path class="w" d="M334 60L340 50L346 60"/><path class="w" d="M334 240L340 250L346 240"/>',
      '<circle cx="300" cy="50" r="4" fill="#111"/><g stroke="#111" stroke-width="2"><path d="M212 258H248"/><path d="M220 264H240"/><path d="M228 270H232"/></g>',
      '<text x="150" y="32" text-anchor="middle">R1 = 2 kΩ</text><text x="235" y="40" text-anchor="middle">I</text><text x="30" y="134" text-anchor="middle">V1</text><text x="30" y="154" text-anchor="middle">12 V</text><text x="302" y="30" text-anchor="middle">A</text><text x="312" y="86">I2</text><text x="414" y="86">I3</text><text x="286" y="152" text-anchor="end">R2 = 6 kΩ</text><text x="414" y="152">R3 = 3 kΩ</text><text x="348" y="142">V_A</text><text x="258" y="266">GND</text>',
      '</svg>',
    ].join('')
    const content = `电路图：\n\n\`\`\`svg\n${source}\n\`\`\``
    const wrapper = mount(MarkdownRenderer, {
      props: { content, autoPlotMath: true, streaming: true },
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.study-inline-svg').exists()).toBe(false)

    await wrapper.setProps({ streaming: false })
    await flushPromises()

    const figure = wrapper.find('.study-inline-svg')
    expect(figure.exists()).toBe(true)
    const svg = figure.find('svg')
    expect(svg.attributes()).toMatchObject({
      viewBox: '0 0 520 300',
      role: 'img',
      'aria-label': '教学示意图',
    })
    expect(svg.findAll('text')).toHaveLength(11)
    expect(svg.find('text').attributes('fill')).toBe('currentColor')
    expect(svg.find('path.w').attributes('stroke')).toBe('currentColor')
    expect(svg.find('marker path').attributes('fill')).toBe('currentColor')
    expect(svg.find('style').exists()).toBe(false)
    wrapper.unmount()
  })

  it('removes active content and external resources from Study SVG diagrams', async () => {
    const source = [
      '<svg viewBox="0 0 100 50" onclick="alert(1)">',
      '<script>alert(1)</script>',
      '<foreignObject><div>unsafe</div></foreignObject>',
      '<image href="https://tracker.example.test/pixel.png"/>',
      '<path style="filter:url(https://tracker.example.test/f)" fill="url(https://tracker.example.test/p)" d="M0 0H10"/>',
      '<path fill="url(#safe-gradient)" d="M0 1H10"/>',
      '</svg>',
    ].join('')
    const wrapper = mount(MarkdownRenderer, {
      props: { content: `\`\`\`svg\n${source}\n\`\`\``, autoPlotMath: true },
    })
    await wrapper.vm.$nextTick()

    const rendered = wrapper.find('.study-inline-svg').html()
    expect(rendered).not.toContain('<script')
    expect(rendered).not.toContain('foreignObject')
    expect(rendered).not.toContain('<image')
    expect(rendered).not.toContain('onclick')
    expect(rendered).not.toContain('tracker.example.test')
    expect(rendered).toContain('url(#safe-gradient)')
    wrapper.unmount()
  })

  it('shows an accessible text fallback when a remote image fails', async () => {
    const wrapper = mount(MarkdownRenderer, { props: {
      content: '![Newton portrait](https://images.example.test/missing.jpg)',
      autoPlotMath: true,
    } })
    await wrapper.vm.$nextTick()
    await wrapper.find('img').trigger('error')

    expect(wrapper.find('img').attributes('hidden')).toBeDefined()
    expect(wrapper.find('.markdown-image-fallback').text()).toBe('图片加载失败：Newton portrait')
    expect(wrapper.find('.markdown-image-fallback').attributes('role')).toBe('status')
    wrapper.unmount()
  })

  it('does not request remote images outside Study mode', async () => {
    const wrapper = mount(MarkdownRenderer, { props: {
      content: '![Reference](https://images.example.test/reference.jpg)',
    } })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.markdown-image-fallback').text()).toContain('远程图片仅在 Study 中显示')
    wrapper.unmount()
  })
})

describe('MarkdownRenderer automatic math plots', () => {
  it('plots supported display functions only when Study enables the feature', async () => {
    const content = '$$f(x)=x^2-2x+1$$'
    const disabled = mount(MarkdownRenderer, { props: { content } })
    await disabled.vm.$nextTick()
    expect(disabled.find('[data-math-auto-plot]').exists()).toBe(false)
    disabled.unmount()

    const enabled = mount(MarkdownRenderer, { props: { content, autoPlotMath: true } })
    await enabled.vm.$nextTick()
    expect(enabled.find('[data-math-auto-plot="function"]').exists()).toBe(true)
    expect(enabled.find('.math-auto-plot-series--0').attributes('d')).toContain('M')
    expect(enabled.find('.math-auto-plot figcaption').text()).toContain('横轴范围 -5 到 5')
    enabled.unmount()
  })

  it('plots explicit sequences as twelve inline points and handles LaTeX fractions', async () => {
    const wrapper = mount(MarkdownRenderer, { props: { content: '$$x_n=\\frac{1}{2n}$$', autoPlotMath: true } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-math-auto-plot="sequence"]').exists()).toBe(true)
    expect(wrapper.findAll('.math-auto-plot-series--0 circle')).toHaveLength(12)
    expect(wrapper.find('.math-auto-plot figcaption').text()).toContain('前 12 项')
    wrapper.unmount()

    const looseFraction = mount(MarkdownRenderer, { props: { content: '$$x_{n}=\\frac 1 {2n}$$', autoPlotMath: true } })
    await looseFraction.vm.$nextTick()
    expect(looseFraction.find('[data-math-auto-plot="sequence"]').exists()).toBe(true)
    expect(looseFraction.findAll('.math-auto-plot-series--0 circle')).toHaveLength(12)
    looseFraction.unmount()
  })

  it('moves eligible inline formulas from the stored lesson to plots after their prose block', async () => {
    const content = [
      '- $x_n = \\dfrac{1}{2^n}$：永远取不到 0，但随 n 增大无限靠近 0。',
      '- $f(x) = \\dfrac{\\sin x}{x}$：在零点没有定义，但极限存在。',
    ].join('\n')
    const wrapper = mount(MarkdownRenderer, { props: { content, autoPlotMath: true } })
    await wrapper.vm.$nextTick()
    const items = wrapper.findAll('li')
    expect(items).toHaveLength(2)
    expect(items[0].find('[data-math-auto-plot="sequence"]').exists()).toBe(true)
    expect(items[0].text()).toContain('永远取不到 0')
    expect(items[1].find('[data-math-auto-plot="function"]').exists()).toBe(true)
    expect(wrapper.find('.math-auto-plot-anchor').exists()).toBe(false)
    wrapper.unmount()
  })

  it('plots common LaTeX functions and multiple aligned series', async () => {
    const content = '$$\\begin{aligned}f(x)&=\\sin x\\\\g(x)&=\\sqrt{x+5}\\end{aligned}$$'
    const wrapper = mount(MarkdownRenderer, { props: { content, autoPlotMath: true } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-math-auto-plot="function"]').exists()).toBe(true)
    expect(wrapper.findAll('.math-auto-plot-series')).toHaveLength(2)
    wrapper.unmount()
  })

  it('turns existing limit formula blocks into an explicit schematic without inventing f(x)', async () => {
    const wrapper = mount(MarkdownRenderer, { props: {
      content: '$$\\lim_{x\\to x_0} f(x)=A$$',
      autoPlotMath: true,
    } })
    await wrapper.vm.$nextTick()
    const plot = wrapper.find('[data-math-auto-plot="limit"]')
    expect(plot.exists()).toBe(true)
    expect(plot.findAll('.math-auto-plot-series')).toHaveLength(2)
    expect(plot.find('.math-auto-plot-limit-point').exists()).toBe(true)
    expect(plot.find('figcaption').text()).toContain('x → x₀')
    expect(plot.find('figcaption').text()).toContain('曲线仅为趋近关系示意')
    wrapper.unmount()
  })

  it('uses discrete points for sequence-limit definition blocks', async () => {
    const wrapper = mount(MarkdownRenderer, { props: {
      content: '$$\\lim_{n\\to\\infty} x_n=a$$',
      autoPlotMath: true,
    } })
    await wrapper.vm.$nextTick()
    const plot = wrapper.find('[data-math-auto-plot="limit"]')
    expect(plot.findAll('.math-auto-plot-limit-sequence circle')).toHaveLength(12)
    expect(plot.find('figcaption').text()).toContain('数列项趋近 a')
    wrapper.unmount()
  })

  it('recognizes the inline lim-limits forms stored in the current lesson', async () => {
    const content = [
      '$\\lim\\limits_{n\\to\\infty}\\dfrac{2n+1}{n+3}=2$',
      '$\\lim\\limits_{x\\to 0}\\dfrac{\\sin x}{x}=1$',
      '$\\lim\\limits_{x\\to\\infty}\\left(1+\\dfrac1x\\right)^x=e$',
    ].join('；')
    const wrapper = mount(MarkdownRenderer, { props: { content, autoPlotMath: true } })
    await wrapper.vm.$nextTick()
    const plots = wrapper.findAll('[data-math-auto-plot="limit"]')
    expect(plots).toHaveLength(3)
    expect(plots[0].findAll('.math-auto-plot-limit-sequence circle')).toHaveLength(12)
    expect(plots[1].find('figcaption').text()).toContain('x → 0')
    expect(plots[2].find('figcaption').text()).toContain('x → ∞')
    wrapper.unmount()
  })

  it('does not plot standalone inline math, equations without a graph variable, or unsupported commands', async () => {
    const wrapper = mount(MarkdownRenderer, { props: {
      content: '内联 $x^2$\n\n$$x^2+2x+1=0$$\n\n$$y=\\unknown{x}$$',
      autoPlotMath: true,
    } })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-math-auto-plot]').exists()).toBe(false)
    wrapper.unmount()
  })
})
