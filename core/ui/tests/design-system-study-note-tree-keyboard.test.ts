import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import StudyNoteTree from '../src/study/StudyNoteTree.vue'

// user:“确保视觉、功能和交互不退化”+(笔记树支持方向键展开、浏览和回到父目录)。
it('navigates and selects notes by keyboard', async () => {
  const onSelect = vi.fn()
  const tree = [{ id: 'folder', title: '课程', path: '课程', kind: 'folder', children: [{ id: 'note', title: '笔记', path: '课程/笔记.md', kind: 'note' }] }, { id: 'other', title: '其他', path: '其他.md', kind: 'note' }]
  const wrapper = mount(StudyNoteTree, { attachTo: document.body, props: { tree: tree as any, onSelect } })
  const folder = wrapper.get('[role="treeitem"][title="课程"]')
  ;(folder.element as HTMLButtonElement).focus()
  await folder.trigger('keydown', { key: 'ArrowRight' })
  expect(folder.attributes('aria-expanded')).toBe('true')
  await folder.trigger('keydown', { key: 'ArrowRight' })
  const note = wrapper.get('[role="treeitem"][title="课程/笔记.md"]')
  expect(document.activeElement).toBe(note.element)
  await note.trigger('click')
  expect(onSelect).toHaveBeenCalledWith(tree[0].children![0])
  await note.trigger('keydown', { key: 'ArrowLeft' })
  expect(document.activeElement).toBe(folder.element)
  await folder.trigger('keydown', { key: 'End' })
  expect((document.activeElement as HTMLElement).title).toBe('其他.md')
  expect(wrapper.findAll('[role="treeitem"][tabindex="0"]')).toHaveLength(1)
  wrapper.unmount()
})
