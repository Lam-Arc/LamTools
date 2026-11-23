import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreUpdateCard from '../src/components/CoreUpdateCard.vue'
describe('update modal control states', () => {
  it('keeps a running install locked while a downloaded update can be closed', async () => {
    const wrapper = mount(CoreUpdateCard, { props: { state: 'downloaded' }, global: { stubs: { Teleport: true } } })
    // user:“更新时可以后台下载。再次点更新键后的卡片继承进度”+(已下载只是“等着装”，
    // 卡片可以关掉；安装包已经校验好，下次打开还能点「立即安装」)。
    expect(wrapper.get('[data-update-confirm]').text()).toBe('立即安装')
    expect((wrapper.get('[data-update-dismiss]').element as HTMLButtonElement).disabled).toBe(false)
    expect((wrapper.get('[data-update-cancel]').element as HTMLButtonElement).disabled).toBe(false)
    await wrapper.setProps({ state: 'installing' })
    expect((wrapper.get('[data-update-dismiss]').element as HTMLButtonElement).disabled).toBe(true)
    expect((wrapper.get('[data-update-cancel]').element as HTMLButtonElement).disabled).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('closed')).toBeUndefined()
    await wrapper.setProps({ state: 'downloading' })
    expect((wrapper.get('[data-update-dismiss]').element as HTMLButtonElement).disabled).toBe(false)
    await wrapper.get('[data-update-cancel]').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    wrapper.unmount()
  })
})
