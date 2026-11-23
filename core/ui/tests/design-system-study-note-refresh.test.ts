import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import NotesManager from '../src/study/NotesManager.vue'
import { normalizeNote } from '../src/study/api'

// user:“确保视觉、功能和交互不退化”+(已保存的笔记应接收更新版本，未保存草稿不能丢失)。
it.each([false, true])('handles a newer remote version with dirty=%s', async dirty => {
  const note = normalizeNote({ id: 'a', title: '示例', body_md: '原文', revision: 1, content_hash: 'h1' })
  const saved = { ...note, bodyMd: '本地已保存', revision: 2, contentHash: 'h2' }
  const wrapper = mount(NotesManager, { props: { notes: [note], selected: note, onSelect: vi.fn(), onSaveDocument: vi.fn().mockResolvedValue(saved) } })
  await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
  const editor = wrapper.get('[aria-label="编辑笔记全文"]')
  await editor.setValue('本地已保存')
  await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click'); await flushPromises()
  if (dirty) await editor.setValue('未保存草稿')
  await wrapper.setProps({ selected: { ...note, bodyMd: '远程更新', revision: 3, contentHash: 'h3' } })
  expect((editor.element as HTMLTextAreaElement).value).toBe(dirty ? '未保存草稿' : '远程更新')
  if (dirty) {
    expect(wrapper.text()).toContain('未保存')
    await wrapper.findAll('button').find(button => button.text() === '放弃')!.trigger('click')
    expect((editor.element as HTMLTextAreaElement).value).toBe('远程更新')
  }
  wrapper.unmount()
})
