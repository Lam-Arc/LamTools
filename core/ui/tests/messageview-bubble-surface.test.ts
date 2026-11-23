import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageView from '../src/components/MessageView.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'
import {
  ASSISTANT_DISPLAY_DEFAULTS,
  normalizeAssistantDisplayPreferences,
  setAssistantDisplayPreferences,
} from '../src/composables/useAssistantDisplayPreferences'

function userMessage(content = '帮我写一份季度报告'): CoreMessage {
  return { id: 'user:surface', role: 'user', content, timestamp: '' }
}

function assistantMessage(content = '一段正文。'): CoreMessage {
  return {
    id: 'assistant:surface',
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
 * user:“全部统一以这个为示例 可复用化，可调参数为胶囊/卡片,填充颜色,是否玻璃”
 * +(用户与助手气泡都套同一份材质：卡片 + 玻璃；没有气泡正文时不受影响)。
 */
describe('MessageView bubble surface', () => {
  it('renders the user bubble on the shared glass card surface', () => {
    const wrapper = mountMessage(userMessage())
    const bubble = wrapper.get('.user-bubble')
    expect(bubble.classes()).toEqual(expect.arrayContaining([
      'message-surface',
      'message-surface--card',
      'message-surface--glass',
      'message-bubble--user',
    ]))
    // 旧的光学玻璃类不再由气泡自己声明，材质只剩一份
    // 角色色用内联变量兜底：类名缺失或构建缓存过期也不会退回灰色
    expect(bubble.attributes('style')).toContain('--message-surface-color')
    expect(bubble.classes()).not.toContain('optical-glass')
  })

  it('keeps the plain answer when assistant bubbles are off', () => {
    const wrapper = mountMessage(assistantMessage())
    expect(wrapper.find('.assistant-surface, .message-surface').exists()).toBe(false)
    expect(wrapper.get('.assistant-answer').text()).toBe('一段正文。')
  })

  it('boxes the assistant answer on the same surface when bubbles are on', () => {
    setAssistantDisplayPreferences({ bubblesEnabled: true })
    const wrapper = mountMessage(assistantMessage())
    const bubble = wrapper.get('.assistant-bubble')
    expect(bubble.classes()).toEqual(expect.arrayContaining([
      'message-surface',
      'message-surface--card',
      'message-surface--glass',
      'message-bubble--assistant',
    ]))
  })

  it('applies the adjustable shape, glass and fill colors from preferences', () => {
    // user:“界面中是否可以设置？颜色与材质配置？”+(设置里的形状/玻璃/颜色在渲染侧生效)
    setAssistantDisplayPreferences({
      bubblesEnabled: true,
      bubbleShape: 'capsule',
      bubbleGlass: false,
      bubbleUserColor: '#123456',
      bubbleAssistantColor: '#00ff00',
    })

    const user = mountMessage(userMessage()).get('.user-bubble')
    expect(user.classes()).toContain('message-surface--capsule')
    expect(user.classes()).toContain('message-surface--solid')
    expect(user.attributes('style')).toContain('--message-surface-fill: #123456')

    const assistant = mountMessage(assistantMessage()).get('.assistant-bubble')
    expect(assistant.classes()).toContain('message-surface--capsule')
    expect(assistant.classes()).toContain('message-surface--solid')
    expect(assistant.attributes('style')).toContain('--message-surface-fill: #00ff00')
  })

  it('drops malformed fill colors and keeps the theme default', () => {
    expect(normalizeAssistantDisplayPreferences({ bubbleUserColor: 'red' }).bubbleUserColor).toBeUndefined()
    expect(normalizeAssistantDisplayPreferences({ bubbleAssistantColor: '#abc' }).bubbleAssistantColor).toBeUndefined()
    expect(normalizeAssistantDisplayPreferences({ bubbleUserColor: '#AABBCC' }).bubbleUserColor).toBe('#aabbcc')
  })
})
