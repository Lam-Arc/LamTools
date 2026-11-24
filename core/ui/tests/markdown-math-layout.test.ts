import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

vi.mock('mermaid', () => ({
  default: { initialize: vi.fn(), render: vi.fn().mockResolvedValue({ svg: '<svg></svg>' }) },
}))

/**
 * Math rendering contract.
 *
 * The user's screenshots (DFT answer: `X_1[k]`, `\sum` with limits, `\frac`,
 * `\delta`, `\omega` terms) show KaTeX output whose structure is recognisably
 * built but whose sub/superscripts and fractions are arranged wrongly. KaTeX's
 * HTML carries the vertical offsets as inline styles on `.vlist > span`, and the
 * inline/tail streaming path and the finished path must produce the same math
 * DOM, so the two possible causes can be separated by a code-level check:
 *
 *  - shape: the emitted HTML must keep KaTeX's vlist structure WITH the inline
 *    `top` offsets (the layout the stylesheet aims at), never a flattened /
 *    re-segmented fragment;
 *  - parity: a formula streamed as a closed segment or an open tail must equal
 *    the finished render byte for byte (no incremental slicing);
 *  - delivery: the KaTeX stylesheet must stay imported by the renderer.
 */

const corpus = [
  '延迟 1 点：$x_1(n)=x_1(n-1)$，时域平移 $\\leftrightarrow$ 频域乘 $W_k$：',
  '',
  '$$X_1[k]=(-j)^k X[k]\\Rightarrow X_1[k]=\\{2,\\,5-j,\\,0,\\,5+j\\}$$',
  '',
  '验算：$\\sum_k X_1[k]=12=4x_1(0)=4(3)=4\\times 3\\ \\checkmark$；共轭对称 $X_1[3]=5+j=X_1^{*}[1]$。',
  '',
  '乘 $e^{j\\pi n/2}=j^n$：$$X_2[k]=X[(k-1)\\bmod 4]=\\{1-5j,\\,2,\\,1+5j,\\,0\\}$$',
  '',
  '时域：$P=\\frac{1}{N}\\sum_{n=0}^{N-1}|x(n)|^2=\\frac{1+4+4+0+9}{4}=3.5$',
  '',
  '$$X(e^{j\\omega})=\\frac{2\\pi}{N}\\sum_{k=-\\infty}^{\\infty}X[k\\bmod 4]\\delta\\!\\left(\\omega-\\frac{2\\pi k}{N}\\right)=\\frac{2\\pi}{N}\\left[2\\delta(\\omega)+(1+5j)\\delta\\!\\left(\\omega-\\frac{2\\pi}{N}\\right)\\right]$$',
].join('\n')

async function render(content: string, streaming: boolean) {
  const wrapper = mount(MarkdownRenderer, { props: { content, streaming } })
  await wrapper.vm.$nextTick()
  const root = wrapper.find('.markdown-body').element
  const math = Array.from(root.querySelectorAll('.katex')).map((node) => node.innerHTML)
  const result = {
    count: math.length,
    errors: root.querySelectorAll('.katex-error').length,
    vlists: root.querySelectorAll('.vlist').length,
    offsetLayers: root.querySelectorAll('.vlist > span[style*="top:"]').length,
    math,
  }
  wrapper.unmount()
  return result
}

describe('math render contract', () => {
  it('keeps the vlist structure and the vertical offsets for the screenshot corpus', async () => {
    const rendered = await render(corpus, false)

    expect(rendered.errors).toBe(0)
    expect(rendered.count).toBe(10)
    // Every script/fraction layer keeps its inline `top` offset and the vlist
    // table chain it needs; a flattened or re-segmented fragment would lose both.
    expect(rendered.vlists).toBeGreaterThanOrEqual(40)
    expect(rendered.offsetLayers).toBeGreaterThanOrEqual(38)
    expect(rendered.offsetLayers).toBeLessThanOrEqual(rendered.vlists)
    for (const html of rendered.math) {
      expect(html).toContain('class="katex-html"')
      expect(html).toContain('class="base"')
      expect(html).not.toContain('katex-error')
    }
  })

  it('renders a streamed formula exactly like the finished one', async () => {
    const streamed = await render(corpus, true)
    const finished = await render(corpus, false)

    expect(streamed.errors).toBe(0)
    expect(streamed.count).toBe(finished.count)
    // Incremental rendering must not slice a formula into independent pieces.
    expect(streamed.math).toEqual(finished.math)
    expect(streamed.vlists).toBe(finished.vlists)
    expect(streamed.offsetLayers).toBe(finished.offsetLayers)
  })

  it('keeps the KaTeX stylesheet imported by the shared renderer', () => {
    const source = readFileSync(
      resolve(import.meta.dirname, '../src/components/MarkdownRenderer.vue'),
      'utf8',
    )
    expect(source).toMatch(/import\s+'katex\/dist\/katex\.min\.css'/)
  })

  /**
   * user:“如图所见 latex 渲染存在问题”+(公式内部的排版不许被公式之外的样式改写)。
   *
   * 这条契约不能靠 jsdom 验证：上下标和分数掉下去是布局结果，jsdom 不做布局。
   * 它保护的是机制本身——KaTeX 用「零高度行 + 行内 top 偏移」叠出上下标与分数，
   * 所以公式内部这些属性必须钉回 KaTeX 自带的值；而且必须写在 @layer 里带 !important，
   * 才不会被插件/主题注入到 document.head 的样式（未分层，权重可能更高）盖掉。
   * 真实浏览器里的 A/B 结果：同一套外部样式下，未隔离的公式被拆散，走渲染器的公式正常。
   */
  it('pins the KaTeX layout inside a cascade layer so外部样式不能改写公式内部排版', () => {
    const source = readFileSync(
      resolve(import.meta.dirname, '../src/components/MarkdownRenderer.vue'),
      'utf8',
    )
    const layer = /@layer\s+sunday-katex-isolation\s*\{([\s\S]*?)\r?\n\}/.exec(source)
    expect(layer).not.toBeNull()
    const rules = layer![1]
    // vlist 链：表格外壳 + 每个零高度行 + 行内格
    expect(rules).toMatch(/\.katex \.vlist-t\)\s*\{[\s\S]*?display:\s*inline-table\s*!important/)
    expect(rules).toMatch(/\.katex \.vlist-r\)\s*\{[\s\S]*?display:\s*table-row\s*!important/)
    expect(rules).toMatch(/\.katex \.vlist\)\s*\{[\s\S]*?(display:\s*table-cell|vertical-align:\s*bottom)\s*!important/)
    expect(rules).toMatch(/\.katex \.vlist > span\)\s*\{[\s\S]*?height:\s*0\s*!important/)
    expect(rules).toMatch(/\.katex \.vlist > span\)\s*\{[\s\S]*?position:\s*relative\s*!important/)
    expect(rules).toMatch(/\.katex \.vlist > span > span\)\s*\{[\s\S]*?display:\s*inline-block\s*!important/)
    // 行高与字距：外部放大行高同样会把每一层推下去
    expect(rules).toMatch(/\.katex\)\s*\{[\s\S]*?line-height:\s*1\.2\s*!important/)
    expect(rules).toMatch(/letter-spacing:\s*normal\s*!important/)
    // \smash 是唯一的例外：它靠行高 0 把内容从行盒里摘出去
    expect(rules).toMatch(/\.katex \.smash[\s\S]*?line-height:\s*0\s*!important/)
  })
})
