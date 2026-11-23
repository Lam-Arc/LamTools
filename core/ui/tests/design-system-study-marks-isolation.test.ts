import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import MarksPanel from '../src/study/MarksPanel.vue'
import { normalizeMark } from '../src/study/api'
import { marks, selectionEvents } from '../src/study/annotations'

// user:“交互测试”+(标记面板可注入隔离数据和操作，不能改变真实会话标记)。
it('uses supplied marks and callbacks without changing shared marks', async () => {
  const mark = normalizeMark({ id: 'sample', anchor: { quote: '示例文本' }, explain: '解释', translate: '译文', thread: [] })
  const before = marks.value
  const onShow = vi.fn(), onJump = vi.fn(), onDelete = vi.fn()
  const wrapper = mount(MarksPanel, { props: { items: [mark], onShow, onJump, onDelete } })
  await wrapper.get('.study-mark-quote').trigger('click')
  await wrapper.get('[aria-label="翻译"]').trigger('click')
  await wrapper.get('[aria-label="删除标记"]').trigger('click')
  expect(onJump).toHaveBeenCalledWith(mark)
  expect(onShow).toHaveBeenCalledWith(mark, 'translate')
  expect(onDelete).toHaveBeenCalledWith(mark)
  expect(marks.value).toBe(before)
  wrapper.unmount()
})

it('keeps the original shared-event behavior when no callbacks are supplied', async () => {
  const previous = marks.value
  const mark = normalizeMark({ id: 'actual', anchor: { quote: '真实标记' }, explain: '解释', thread: [] })
  const onOpen = vi.fn()
  selectionEvents.addEventListener('open', onOpen)
  marks.value = [mark]
  const wrapper = mount(MarksPanel)
  await wrapper.get('[aria-label="解释"]').trigger('click')
  expect((onOpen.mock.calls[0][0] as CustomEvent).detail).toEqual({ mark, action: 'explain' })
  wrapper.unmount(); marks.value = previous; selectionEvents.removeEventListener('open', onOpen)
})
