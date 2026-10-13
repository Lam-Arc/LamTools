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
})
