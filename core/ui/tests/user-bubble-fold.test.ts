import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import ChatThread from '../src/components/ChatThread.vue'
import { estimateUserBubbleLines, userBubbleShouldFold } from '../src/helpers/userBubbleFold'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

const __dirname = dirname(fileURLToPath(import.meta.url))
const testTransport = createFakeTransport()

function mountChatThread(props: any = {}) {
  return mount(ChatThread, {
    props: { transport: testTransport, ...props },
  })
}

function userMessage(content: string, id = 'turn-fold:user'): CoreMessage {
  return { id, role: 'user', content, timestamp: '' }
}

function linesOf(count: number): string {
  return Array.from({ length: count }, (_, i) => `第${i + 1}行内容`).join('\n')
}

describe('user bubble fold estimate', () => {
  it('counts hard line breaks and wrapped width', () => {
    expect(estimateUserBubbleLines('')).toBe(0)
    expect(estimateUserBubbleLines('短消息')).toBe(1)
    expect(estimateUserBubbleLines('a\nb')).toBe(2)
    expect(estimateUserBubbleLines('a'.repeat(84))).toBe(1)
    expect(estimateUserBubbleLines('a'.repeat(85))).toBe(2)
    // CJK 按双宽计：42 个汉字一行，43 个换行。
    expect(estimateUserBubbleLines('汉'.repeat(42))).toBe(1)
    expect(estimateUserBubbleLines('汉'.repeat(43))).toBe(2)
  })

  it('folds only beyond the threshold', () => {
    expect(userBubbleShouldFold(linesOf(8))).toBe(false)
    expect(userBubbleShouldFold(linesOf(9))).toBe(true)
    expect(userBubbleShouldFold('a'.repeat(400))).toBe(false)
    expect(userBubbleShouldFold('a'.repeat(800))).toBe(true)
    // 同样字符数的 CJK 文本更宽，会折叠。
    expect(userBubbleShouldFold('汉'.repeat(400))).toBe(true)
  })
})

describe('user bubble auto fold', () => {
  it('keeps a short message unfolded without any toggle', () => {
    const wrapper = mountChatThread({ messages: [userMessage('帮我写一份季度报告')] })

    const bubble = wrapper.get('.user-bubble')
    expect(bubble.classes()).not.toContain('user-bubble--folded')
    expect(wrapper.find('[data-user-bubble-fold]').exists()).toBe(false)
  })

  it('folds a long message by default and offers the expand toggle', () => {
    const wrapper = mountChatThread({ messages: [userMessage(linesOf(12))] })

    const bubble = wrapper.get('.user-bubble')
    expect(bubble.classes()).toContain('user-bubble--folded')
    const toggle = wrapper.get('[data-user-bubble-fold]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toBe('展开')
    // 折叠的只是展示：折叠前的文字仍在气泡里（选区、复制语义不变）。
    expect(bubble.text()).toContain('第12行内容')
  })

  it('expands on click and folds back on the second click', async () => {
    const wrapper = mountChatThread({ messages: [userMessage(linesOf(12))] })

    const toggle = () => wrapper.get('[data-user-bubble-fold]')
    await toggle().trigger('click')
    expect(wrapper.get('.user-bubble').classes()).not.toContain('user-bubble--folded')
    expect(toggle().attributes('aria-expanded')).toBe('true')
    expect(toggle().text()).toBe('收起')

    await toggle().trigger('click')
    expect(wrapper.get('.user-bubble').classes()).toContain('user-bubble--folded')
    expect(toggle().attributes('aria-expanded')).toBe('false')
  })

  it('remembers the expanded message independently per message id', async () => {
    const wrapper = mountChatThread({
      messages: [userMessage(linesOf(12), 'turn-a:user'), userMessage(linesOf(12), 'turn-b:user')],
    })

    const bubbles = wrapper.findAll('.user-bubble')
    expect(bubbles.map(bubble => bubble.classes())).toEqual([
      expect.arrayContaining(['user-bubble--folded']),
      expect.arrayContaining(['user-bubble--folded']),
    ])

    await wrapper.findAll('[data-user-bubble-fold]')[0]!.trigger('click')
    expect(wrapper.findAll('.user-bubble')[0]!.classes()).not.toContain('user-bubble--folded')
    expect(wrapper.findAll('.user-bubble')[1]!.classes()).toContain('user-bubble--folded')
  })

  it('estimates fold from the visible text, not the folded reference prefix', () => {
    const prefix = linesOf(10)
    const content = `${prefix}\n帮我写一份季度报告`
    const msg: CoreMessage = {
      id: 'turn-ref:user',
      role: 'user',
      content,
      timestamp: '',
      metadata: { auxiliary_reference_prefix: prefix },
    }
    const folded = mountChatThread({ messages: [msg] })
    // 引用前缀在原文栏展示、不占气泡：可见文本很短，不折叠。
    expect(folded.get('.user-bubble').classes()).not.toContain('user-bubble--folded')
    expect(folded.find('[data-user-bubble-fold]').exists()).toBe(false)

    const withoutMetadata: CoreMessage = { ...msg, metadata: {} }
    const raw = mountChatThread({ messages: [withoutMetadata] })
    // 同样的内容没有原文栏承接时按完整内容估算，正常折叠。
    expect(raw.get('.user-bubble').classes()).toContain('user-bubble--folded')
  })

  it('keeps full content on fork/rollback while the bubble is folded', async () => {
    const content = linesOf(12)
    const wrapper = mountChatThread({ messages: [userMessage(content)], messageActions: true })

    expect(wrapper.get('.user-bubble').classes()).toContain('user-bubble--folded')
    await wrapper.get('[data-user-fork]').trigger('click')
    await wrapper.get('[data-user-rollback]').trigger('click')
    expect(wrapper.emitted('fork-message')).toEqual([[{ turnId: 'turn-fold', content }]])
    expect(wrapper.emitted('rollback-message')).toEqual([[{ turnId: 'turn-fold', content }]])
  })
})

describe('user bubble fold styles', () => {
  it('clamps the folded preview with a bottom fade and reuses the button recipe', () => {
    const editing = readFileSync(resolve(__dirname, '../src/styles/chat-thread-editing.css'), 'utf8')

    // 折叠态只保留 6 行并向下渐隐，提示还有更多内容。
    expect(editing).toMatch(/\.user-bubble--folded \.user-bubble-text\s*\{[^}]*-webkit-line-clamp:\s*6/)
    expect(editing).toMatch(/\.user-bubble--folded \.user-bubble-text\s*\{[^}]*mask-image:[^;]*to bottom/)
    // 展开/收起按钮沿用“透明 → 悬停加亮”的现有配方与状态档位。
    expect(editing).toMatch(/\.user-bubble-fold:hover[\s\S]*?var\(--alpha-hover\)/)
    expect(editing).toMatch(/\.user-bubble-fold:active[\s\S]*?var\(--alpha-active\)/)
  })
})
