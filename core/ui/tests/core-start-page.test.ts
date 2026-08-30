import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CoreStartPage from '../src/components/CoreStartPage.vue'

describe('CoreStartPage', () => {
  it('guides a workspace without projects to create or open one', async () => {
    const wrapper = mount(CoreStartPage)

    expect(wrapper.attributes('data-state')).toBe('no-project')
    expect(wrapper.text()).toContain('准备开干！')
    expect(wrapper.find('[data-start-new-session]').exists()).toBe(false)
    expect(wrapper.find('.core-start-page-recent').exists()).toBe(false)

    await wrapper.get('[data-start-new-project]').trigger('click')
    await wrapper.get('[data-start-open-project]').trigger('click')

    expect(wrapper.emitted('new-project')).toEqual([[]])
    expect(wrapper.emitted('open-project')).toEqual([[]])
  })

  it('gives an existing project without a session a focused new-session entry', async () => {
    const wrapper = mount(CoreStartPage, { props: { hasProject: true } })

    expect(wrapper.attributes('data-state')).toBe('project-no-session')
    expect(wrapper.find('[data-start-new-project]').exists()).toBe(false)
    expect(wrapper.get('[data-start-open-project]').text()).toBe('打开其他项目')

    await wrapper.get('[data-start-new-session]').trigger('click')
    expect(wrapper.emitted('new-session')).toEqual([[]])
  })

  it('keeps recent projects keyboard-native and exposes the full path as a hint', async () => {
    const wrapper = mount(CoreStartPage, {
      props: {
        recentProjects: [{
          id: 'project-1',
          name: 'LamTools',
          workRoot: 'E:\\LamTools',
          openedAt: new Date().toISOString(),
        }],
      },
    })
    const entry = wrapper.get('[data-recent-project="project-1"]')

    expect(entry.element.tagName).toBe('BUTTON')
    expect(entry.attributes('title')).toBe('E:\\LamTools')
    await entry.trigger('click')

    expect(wrapper.emitted('open-recent-project')).toEqual([['project-1']])
  })
})
