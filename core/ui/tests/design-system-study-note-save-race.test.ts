import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import NotesManager from '../src/study/NotesManager.vue'
import { normalizeNote } from '../src/study/api'

// user:“确保视觉、功能和交互不退化”+(保存期间继续输入时，响应不能覆盖较新的草稿)。
it('preserves edits made while an earlier save is pending', async () => {
  const note = normalizeNote({ id: 'a', title: '示例', path: 'a.md', body_md: '原文', revision: 1, content_hash: 'h1', resources: [], resource_ids: [], links: [], backlinks: [], locks: [] })
  let finish!: (value: unknown) => void
  const onSaveDocument = vi.fn(() => new Promise(resolve => { finish = resolve }))
  const wrapper = mount(NotesManager, { props: { notes: [note], selected: note, onSelect: vi.fn(), onSaveDocument } })
  await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
  const editor = wrapper.get('[aria-label="编辑笔记全文"]')
  await editor.setValue('第一版')
  await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click')
  await editor.setValue('更新的草稿')
  expect(wrapper.findAll('button').find(button => button.text() === '保存')!.attributes('disabled')).toBeDefined()
  finish({ ...note, bodyMd: '第一版', revision: 2, contentHash: 'h2' }); await flushPromises()
  expect((editor.element as HTMLTextAreaElement).value).toBe('更新的草稿')
  expect(wrapper.text()).toContain('未保存')
  await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click')
  expect(onSaveDocument).toHaveBeenLastCalledWith(note, '更新的草稿', expect.objectContaining({ revision: 2, contentHash: 'h2' }))
  wrapper.unmount()
})

it('treats reverting to the original text during save as a new unsaved change', async () => {
  const note = normalizeNote({ id: 'a', title: '示例', path: 'a.md', body_md: '原文', revision: 1, content_hash: 'h1', resources: [], resource_ids: [], links: [], backlinks: [], locks: [] })
  let finish!: (value: unknown) => void
  const wrapper = mount(NotesManager, { props: { notes: [note], selected: note, onSelect: vi.fn(), onSaveDocument: () => new Promise(resolve => { finish = resolve }) } })
  await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
  const editor = wrapper.get('[aria-label="编辑笔记全文"]')
  await editor.setValue('第一版')
  await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click')
  await editor.setValue('原文')
  finish({ ...note, bodyMd: '第一版', revision: 2, contentHash: 'h2' }); await flushPromises()
  expect((editor.element as HTMLTextAreaElement).value).toBe('原文')
  expect(wrapper.text()).toContain('未保存')
  wrapper.unmount()
})

it('does not report a previous note save on a newly selected note', async () => {
  const first = normalizeNote({ id: 'a', title: '第一篇', body_md: '原文', revision: 1, content_hash: 'a1' })
  const second = normalizeNote({ id: 'b', title: '第二篇', body_md: '其他内容', revision: 1, content_hash: 'b1' })
  let finish!: (value: unknown) => void
  const wrapper = mount(NotesManager, { props: { notes: [first, second], selected: first, onSelect: vi.fn(), onSaveDocument: () => new Promise(resolve => { finish = resolve }) } })
  await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
  await wrapper.get('[aria-label="编辑笔记全文"]').setValue('第一篇修改')
  await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click')
  await wrapper.setProps({ selected: second })
  finish({ ...first, bodyMd: '第一篇修改', revision: 2, contentHash: 'a2' }); await flushPromises()
  expect(wrapper.text()).toContain('第二篇')
  expect(wrapper.text()).not.toContain('已保存')
  wrapper.unmount()
})
