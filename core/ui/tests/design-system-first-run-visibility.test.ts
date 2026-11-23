import { afterEach, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import FirstRunChecklist from '../src/components/FirstRunChecklist.vue'

// user:“确保视觉、功能和交互不退化”+(完成态隐藏后再次显示时仍应自动收起)。
afterEach(() => vi.useRealTimers())
it('starts the completion timer only while the finished checklist is visible', async () => {
  vi.useFakeTimers()
  const wrapper = mount(FirstRunChecklist, { props: { visible: false, hasProvider: true, hasProject: true, hasSession: true, firstMessageSent: true } })
  vi.advanceTimersByTime(5000)
  expect(wrapper.emitted('finished')).toBeUndefined()
  await wrapper.setProps({ visible: true }); await nextTick()
  vi.advanceTimersByTime(4200)
  expect(wrapper.emitted('finished')).toHaveLength(1)
  await wrapper.setProps({ visible: false }); await wrapper.setProps({ visible: true })
  vi.advanceTimersByTime(4200)
  expect(wrapper.emitted('finished')).toHaveLength(2)
  wrapper.unmount()
})
