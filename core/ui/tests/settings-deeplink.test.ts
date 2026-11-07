/**
 * 设置直达：托盘/右键 → 分区 + 稳定对象 ID。
 *
 * user:“托盘‘桌宠设置’、桌宠右键‘编辑角色’可直达对应工作台、选中对象”+
 * (跨窗口只传 ID；分区不匹配时不能被另一个页面提前消费。)
 */
import { afterEach, describe, expect, it } from 'vitest'
import {
  consumeSettingsDeepLink,
  onSettingsDeepLink,
  publishSettingsDeepLink,
} from '@/helpers/settingsDeepLink.ts'

afterEach(() => {
  localStorage.clear()
})

describe('设置工作台直达', () => {
  it('同分区能取到对象 ID，取出后不重复生效', () => {
    publishSettingsDeepLink('pet', 'blocky-1')
    expect(consumeSettingsDeepLink('pet')).toBe('blocky-1')
    expect(consumeSettingsDeepLink('pet')).toBe('')
  })

  it('分区不匹配时保留给另一个工作台', () => {
    publishSettingsDeepLink('ping', 'sector-tools')
    expect(consumeSettingsDeepLink('pet')).toBe('')
    expect(consumeSettingsDeepLink('ping')).toBe('sector-tools')
  })

  it('已挂载页面收到同窗口事件', () => {
    const received: string[] = []
    const off = onSettingsDeepLink('pet', id => received.push(id))
    publishSettingsDeepLink('pet', 'pet-9')
    publishSettingsDeepLink('ping', 'sector-1')
    off()
    publishSettingsDeepLink('pet', 'pet-10')
    expect(received).toEqual(['pet-9'])
  })

  it('过期记录不会错误选中旧对象', () => {
    localStorage.setItem('lamtools.core.settings.deep-link', JSON.stringify({
      section: 'pet', objectId: 'old', at: Date.now() - 120_000,
    }))
    expect(consumeSettingsDeepLink('pet')).toBe('')
  })
})
