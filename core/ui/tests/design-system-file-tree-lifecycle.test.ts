import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreSplitFileTree from '../src/components/CoreSplitFileTree.vue'

// user:“确保视觉、功能和交互不退化”+(切换项目丢弃旧结果，读取失败可重试)。
describe('split file tree lifecycle', () => {
  it('loads the new root and ignores a late response from the previous project', async () => {
    let finishOld!: (value: Array<{ name: string; path: string; directory: boolean }>) => void
    const listFiles = vi.fn((root: string) => root === 'old'
      ? new Promise<Array<{ name: string; path: string; directory: boolean }>>(resolve => { finishOld = resolve })
      : Promise.resolve([{ name: '新文件', path: 'new/file', directory: false }]))
    const wrapper = mount(CoreSplitFileTree, { props: { root: 'old', listFiles } })
    await wrapper.setProps({ root: 'new' }); await flushPromises()
    expect(wrapper.text()).toContain('新文件')
    finishOld([{ name: '旧文件', path: 'old/file', directory: false }]); await flushPromises()
    expect(wrapper.text()).not.toContain('旧文件')
    expect(wrapper.text()).toContain('新文件')
    wrapper.unmount()
  })
  it('offers a retry for the directory that failed', async () => {
    let fail = true
    const listFiles = vi.fn(async (_root: string, path: string) => {
      if (path === 'root') return [{ name: '目录', path: 'root/folder', directory: true }]
      if (fail) throw Error('读取失败')
      return [{ name: '笔记', path: 'root/folder/note', directory: false }]
    })
    const wrapper = mount(CoreSplitFileTree, { props: { root: 'root', listFiles } }); await flushPromises()
    await wrapper.get('[role="treeitem"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('读取失败')
    fail = false
    await wrapper.get('[role="alert"] button').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('笔记')
    expect(listFiles).toHaveBeenLastCalledWith('root', 'root/folder')
    wrapper.unmount()
  })
})
