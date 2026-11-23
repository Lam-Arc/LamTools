// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import LibraryHomeView from '@/components/LibraryHomeView.vue'
import { homeQuickActionIds } from '@/split/browserHome'

it('opens project files and materials from the same library while retaining file navigation', async () => {
  const openProjectFile = vi.fn()
  const listFiles = vi.fn(async (_root: string, folder: string) => folder === 'E:/sample'
    ? [{ name: 'notes', path: 'E:/sample/notes', directory: true }]
    : [{ name: 'readme.md', path: 'E:/sample/notes/readme.md', directory: false }])
  const wrapper = mount(LibraryHomeView, {
    props: { client: {} as never, projectId: 'sample', workRoot: 'E:/sample', platform: 'desktop', requestRpc: async () => ({}), listFiles, openProjectFile },
    global: { stubs: { MaterialsView: true } },
  })
  try {
    expect(wrapper.find('[data-library-materials]').exists()).toBe(true)
    await wrapper.get('[data-library-section="files"]').trigger('click')
    await flushPromises()
    await wrapper.get('[role="treeitem"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-library-section="materials"]').trigger('click')
    await wrapper.get('[data-library-section="files"]').trigger('click')
    await wrapper.findAll('[role="treeitem"]')[1].trigger('click')
    expect(openProjectFile).toHaveBeenCalledWith('E:/sample/notes/readme.md', { workRoot: 'E:/sample', projectId: 'sample' })
    expect(listFiles).toHaveBeenCalledTimes(2)
  } finally { wrapper.unmount() }
})

it('offers one resource entry on the browser home', () => {
  expect(homeQuickActionIds({ hasController: true, hasPane: true })).toEqual(['web', 'media'])
})
