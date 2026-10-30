import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageView from '../src/components/MessageView.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'
import {
  ASSISTANT_DISPLAY_DEFAULTS,
  setAssistantDisplayPreferences,
} from '../src/composables/useAssistantDisplayPreferences'
import { ASSISTANT_BUBBLE_MARKER } from '../src/helpers/assistantBubbles'

function message(content: string): CoreMessage {
  return {
    id: 'assistant:bubble',
    role: 'assistant',
    content,
    timestamp: '',
    parts: [{
      id: 'p-answer',
      partType: 'model_text',
      status: 'completed',
      label: '正文',
      content,
    }],
  }
}

function mountMessage(msg: CoreMessage) {
  return mount(MessageView, { props: { msg, transport: createFakeTransport() } })
}

afterEach(() => {
  setAssistantDisplayPreferences(ASSISTANT_DISPLAY_DEFAULTS)
})

/**
 * user:“Assistant 可选择是否使用消息气泡”“支持自定义 Assistant 显示名称和头像”
 * “支持开启或关闭自动气泡拆分”+(默认保持无气泡正文；只有开关打开才出现气泡、
 * 自定义名称与头像，且拆分不改变消息本身)
 */
describe('MessageView assistant display preferences', () => {
  it('keeps the plain answer and no bubble chrome by default', () => {
    const wrapper = mountMessage(message('一段正文。'))
    expect(wrapper.find('.assistant-answer').text()).toBe('一段正文。')
    expect(wrapper.find('.assistant-bubble').exists()).toBe(false)
    expect(wrapper.find('.assistant-avatar').exists()).toBe(false)
    expect(wrapper.find('.assistant-label').text()).toBe('Assistant')
  })

  it('renders bubbles, custom name and avatar when enabled', () => {
    setAssistantDisplayPreferences({
      bubblesEnabled: true,
      name: 'Sunday',
      avatar: 'https://example.com/avatar.png',
    })
    const wrapper = mountMessage(message('一段正文。'))
    expect(wrapper.findAll('.assistant-bubble')).toHaveLength(1)
    expect(wrapper.find('.assistant-avatar img').attributes('src')).toBe('https://example.com/avatar.png')
    expect(wrapper.find('.assistant-label').text()).toBe('Sunday')
  })

  it('renders boxed bubbles on the shared low-transmission glass surface', () => {
    // user:“气泡连上低透玻璃样式”+(盒子气泡复用 .optical-glass 底材，
    // 不再自己写一套半透明底色；未开气泡的正文不套玻璃)
    setAssistantDisplayPreferences({ bubblesEnabled: true })
    const boxed = mountMessage(message('一段正文。'))
    const bubble = boxed.get('.assistant-bubble')
    expect(bubble.classes()).toContain('optical-glass')
    expect(bubble.classes()).toContain('optical-glass--low-trans')
    boxed.unmount()

    setAssistantDisplayPreferences({ bubblesEnabled: false, splitEnabled: true })
    const plain = mountMessage(message('第一段。\n\n## 小节\n\n第二段。'))
    expect(plain.get('.assistant-bubble').classes()).not.toContain('optical-glass')
    plain.unmount()
  })

  it('applies the adjustable avatar size and roundness', () => {
    // user:“头上头像显示大小太小了 设成可调节，裁切也是圆角率可调节”+
    // (尺寸与圆角率来自显示偏好，圆角率 100 对应 50% 半径＝圆形)
    setAssistantDisplayPreferences({ bubblesEnabled: true, name: 'Sunday', avatarSize: 48, avatarRoundness: 40 })
    const wrapper = mountMessage(message('一段正文。'))
    const style = wrapper.get('.assistant-avatar').attributes('style') || ''
    expect(style).toContain('--assistant-avatar-size: 48px')
    expect(style).toContain('--assistant-avatar-radius: 20%')
    wrapper.unmount()
  })

  it('falls back to the name initial when no avatar is configured', () => {
    setAssistantDisplayPreferences({ bubblesEnabled: true, name: 'Sunday' })
    const wrapper = mountMessage(message('一段正文。'))
    expect(wrapper.find('.assistant-avatar img').exists()).toBe(false)
    expect(wrapper.find('.assistant-avatar__initial').text()).toBe('S')
  })

  it('splits on the model marker without showing the marker', async () => {
    setAssistantDisplayPreferences({ bubblesEnabled: true })
    const wrapper = mountMessage(message(`第一段。\n${ASSISTANT_BUBBLE_MARKER}\n第二段。`))
    const bubbles = wrapper.findAll('.assistant-bubble')
    expect(bubbles).toHaveLength(2)
    expect(bubbles[0].text()).toBe('第一段。')
    expect(bubbles[1].text()).toBe('第二段。')
    expect(wrapper.find('.assistant-answer').text()).not.toContain(ASSISTANT_BUBBLE_MARKER)
    wrapper.unmount()
  })

  it('splits structurally only when auto split is on', () => {
    const content = '第一段。\n\n## 小节\n\n第二段。'
    const off = mountMessage(message(content))
    expect(off.findAll('.assistant-bubble')).toHaveLength(0)
    off.unmount()

    setAssistantDisplayPreferences({ splitEnabled: true })
    const on = mountMessage(message(content))
    expect(on.findAll('.assistant-bubble')).toHaveLength(2)
    expect(on.findAll('.assistant-bubble')[1].text()).toContain('小节')
    on.unmount()
  })

  it('keeps thinking and tool progress in the process area, not in bubbles', () => {
    setAssistantDisplayPreferences({ bubblesEnabled: true, splitEnabled: true })
    const msg: CoreMessage = {
      id: 'assistant:process',
      role: 'assistant',
      content: '最终回答。',
      timestamp: '',
      parts: [
        { id: 'p-reason', partType: 'reasoning', status: 'completed', label: '思考', content: '内部推理。' },
        { id: 'p-answer', partType: 'model_text', status: 'completed', label: '正文', content: '最终回答。' },
      ],
    }
    const wrapper = mountMessage(msg)
    expect(wrapper.find('.assistant-answer').text()).not.toContain('内部推理。')
    expect(wrapper.find('.assistant-process').exists() || wrapper.find('.process-stream').exists() || wrapper.find('.process-summary').exists()).toBe(true)
  })
})
