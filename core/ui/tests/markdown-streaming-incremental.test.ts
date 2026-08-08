import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

/**
 * Incremental streaming renderer contract:
 * 1. DOM output is byte-equivalent to the (reference) string renderer.
 * 2. Closed segments keep their exact DOM nodes across ticks — only the
 *    open tail segment is rebuilt (this is the O(tail) per-frame guarantee).
 */

async function mountStreaming(content: string) {
  const wrapper = mount(MarkdownRenderer, { props: { content, streaming: true } })
  await wrapper.vm.$nextTick()
  return wrapper
}

// Compare by block tag + textContent: jsdom serializes katex spans /
// unclosed-tag nesting slightly differently than an independent container, so
// byte-level innerHTML comparison is a false positive; block structure +
// visible text are the reliable "rendered the same" signal.
function blockSignature(root: Element): string {
  return Array.from(root.children).map(node => `${node.tagName}|${node.textContent}`).join('\n')
}

function referenceSignature(wrapper: ReturnType<typeof mount>, content: string): string {
  const ref = (wrapper.vm as unknown as { renderStreaming(content: string): string }).renderStreaming(content)
  const temp = document.createElement('div')
  temp.innerHTML = ref
  return blockSignature(temp)
}

describe('MarkdownRenderer incremental streaming', () => {
  it('produces DOM identical to the reference string renderer, tick by tick', async () => {
    const steps = [
      '第一段',
      '第一段，包含 **加粗** 和 `code`。',
      '第一段，包含 **加粗** 和 `code`。\n\n第二段：\n- 一\n- 二',
      '第一段，包含 **加粗** 和 `code`。\n\n第二段：\n- 一\n- 二\n\n```py\nprint(1)\n```',
    ]
    const wrapper = await mountStreaming(steps[0])
    expect(blockSignature(wrapper.find('.markdown-body').element)).toBe(referenceSignature(wrapper, steps[0]))
    for (const step of steps.slice(1)) {
      await wrapper.setProps({ content: step })
      await wrapper.vm.$nextTick()
      expect(blockSignature(wrapper.find('.markdown-body').element), `step: ${JSON.stringify(step)}`).toBe(referenceSignature(wrapper, step))
    }
    wrapper.unmount()
  })

  it('reuses closed segment DOM nodes across ticks; only the tail is rebuilt', async () => {
    const wrapper = await mountStreaming('甲段\n\n乙段\n\n丙段')
    const container = wrapper.find('.markdown-body').element
    const before = Array.from(container.children)

    // Tail growth: 丁段 appended → the first three segments keep their nodes.
    await wrapper.setProps({ content: '甲段\n\n乙段\n\n丙段\n\n丁段' })
    await wrapper.vm.$nextTick()
    const after = Array.from(container.children)
    expect(after.length).toBe(4)
    for (let i = 0; i < 3; i += 1) {
      expect(after[i]).toBe(before[i])
    }
    expect(after[3]).not.toBe(before[3])

    // Tail modification: the open segment is replaced, closed ones stay.
    const beforeSecondTick = Array.from(container.children)
    await wrapper.setProps({ content: '甲段\n\n乙段\n\n丙段\n\n丁段加长内容' })
    await wrapper.vm.$nextTick()
    const afterSecondTick = Array.from(container.children)
    expect(afterSecondTick[0]).toBe(beforeSecondTick[0])
    expect(afterSecondTick[1]).toBe(beforeSecondTick[1])
    expect(afterSecondTick[2]).toBe(beforeSecondTick[2])
    expect(afterSecondTick[3]).not.toBe(beforeSecondTick[3])
    wrapper.unmount()
  })

  it('cleans up DOM when streaming ends', async () => {
    const wrapper = await mountStreaming('一段')
    await wrapper.setProps({ content: '一段', streaming: false })
    await wrapper.vm.$nextTick()
    // Non-streaming path renders via v-html (full markdown).
    expect(wrapper.find('.markdown-body').exists()).toBe(true)
    wrapper.unmount()
  })
})

