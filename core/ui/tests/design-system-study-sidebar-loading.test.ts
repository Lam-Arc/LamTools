import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import StudySidebar from '../src/study/StudySidebar.vue'

describe('study sidebar loading', () => {
  it('reports a failed course load and retries without collapsing the course', async () => {
    const loadChildren = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([
      { id: 'n', name: '知识点', learnable: true, progressRole: 'unit', assessment: 'unassessed', mastery: null },
    ])
    const wrapper = mount(StudySidebar, { props: { courses: [{ id: 'c', name: '课程', total: 1, passed: 0 }], active: '', select: vi.fn(), loadChildren } })
    await wrapper.get('button[aria-label="展开 课程"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('加载失败')
    expect(wrapper.get('button[aria-label="收起 课程"]').attributes('aria-expanded')).toBe('true')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('知识点')
    expect(loadChildren).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('reports and retries a nested module independently', async () => {
    const loadChildren = vi.fn().mockResolvedValueOnce([
      { id: 'm', name: '模块', entity: 'module', learnable: false, progressRole: 'aggregate', assessment: 'unassessed', mastery: null, course_id: 'c' },
    ]).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([
      { id: 'n', name: '知识点', learnable: true, progressRole: 'unit', assessment: 'unassessed', mastery: null },
    ])
    const wrapper = mount(StudySidebar, { props: { courses: [{ id: 'c', name: '课程', total: 1, passed: 0 }], active: '', select: vi.fn(), loadChildren } })
    await wrapper.get('button[aria-label="展开 课程"]').trigger('click')
    await flushPromises()
    await wrapper.get('button[aria-label="展开 模块"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('加载失败')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('知识点')
    expect(loadChildren).toHaveBeenLastCalledWith({ id: 'm', kind: 'module', courseId: 'c' })
    wrapper.unmount()
  })
})
