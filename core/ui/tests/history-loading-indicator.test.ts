import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import HistoryLoadingIndicator from '../src/components/HistoryLoadingIndicator.vue'

describe('HistoryLoadingIndicator', () => {
  it('renders five staggered message skeletons with an accessible loading state', () => {
    const wrapper = mount(HistoryLoadingIndicator, { props: { active: true } })

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.attributes('aria-label')).toBe('正在加载历史消息')
    expect(wrapper.findAll('[data-history-loading-bubble]')).toHaveLength(5)
    expect(wrapper.findAll('.history-loading-line').length).toBeGreaterThan(0)
    expect((wrapper.element as HTMLElement).style.display).toBe('grid')

    wrapper.unmount()
  })
})
