import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CoreUpdateCard from '../src/components/CoreUpdateCard.vue'

function mountCard(props: Record<string, unknown> = {}) {
  return mount(CoreUpdateCard, {
    props: { currentVersion: '0.3.13', latestVersion: '0.3.14', ...props },
    global: { stubs: { teleport: true } },
  })
}

describe('CoreUpdateCard', () => {
  it('names both versions and shows the release notes when the manifest has them', () => {
    const wrapper = mountCard({ notes: '修好了引导丢失的问题。' })

    const versions = wrapper.get('[data-update-versions]').text()
    expect(versions).toContain('0.3.13')
    expect(versions).toContain('0.3.14')
    expect(wrapper.get('[data-update-notes]').text()).toBe('修好了引导丢失的问题。')
    expect(wrapper.get('[data-update-card]').attributes('role')).toBe('dialog')
  })

  it('hides the notes block when the manifest carries none', () => {
    const wrapper = mountCard()

    expect(wrapper.find('[data-update-notes]').exists()).toBe(false)
  })

  it('offers 取消 and 更新 before anything started, and 更新 asks to proceed', async () => {
    const wrapper = mountCard()

    expect(wrapper.get('[data-update-cancel]').text()).toBe('取消')
    expect(wrapper.get('[data-update-confirm]').text()).toBe('更新')
    expect((wrapper.get('[data-update-confirm]').element as HTMLButtonElement).disabled).toBe(false)

    await wrapper.get('[data-update-confirm]').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('shows 下载 with a percentage while it runs, and disabling the primary action', () => {
    const wrapper = mountCard({ state: 'downloading', received: 24_000_000, total: 58_000_000 })

    expect(wrapper.get('[data-update-percent]').text()).toBe('下载 41%')
    expect((wrapper.get('[data-update-confirm]').element as HTMLButtonElement).disabled).toBe(true)
    expect(wrapper.get('[data-update-cancel]').text()).toBe('取消下载')
  })

  it('cancels a running download: the host is told, then the card collapses', async () => {
    const wrapper = mountCard({ state: 'downloading', received: 1, total: 2 })

    await wrapper.get('[data-update-cancel]').trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('closed')).toHaveLength(1)
  })

  it('reports an install in progress and refuses to be dismissed', async () => {
    const wrapper = mountCard({ state: 'installing' })

    expect(wrapper.get('[data-update-confirm]').text()).toBe('正在安装…')
    expect(wrapper.get('[data-update-card-status]').text()).toContain('自动重新打开')

    await wrapper.get('[data-update-cancel]').trigger('click')
    await wrapper.get('[data-update-dismiss]').trigger('click')

    // 安装已经开始：不取消、不关闭，用户看到的就是正在发生的事。
    expect(wrapper.emitted('cancel')).toBeUndefined()
    expect(wrapper.emitted('closed')).toBeUndefined()
  })

  it('keeps a failure visible and offers a retry', async () => {
    const wrapper = mountCard({ state: 'failed', error: '下载安装包失败：连接被中断' })

    expect(wrapper.get('[data-update-card-error]').text()).toContain('连接被中断')
    expect(wrapper.get('[data-update-confirm]').text()).toBe('重试')

    await wrapper.get('[data-update-confirm]').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('closes on Escape before anything started', async () => {
    const wrapper = mountCard()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('cancel')).toBeUndefined()
    expect(wrapper.emitted('closed')).toHaveLength(1)
  })

  it('closes when the scrim is clicked', async () => {
    const wrapper = mountCard()

    await wrapper.get('[data-update-scrim]').trigger('click')

    expect(wrapper.emitted('closed')).toHaveLength(1)
  })
})
