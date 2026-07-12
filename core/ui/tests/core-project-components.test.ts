import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CoreAgentsEditor from '../src/components/CoreAgentsEditor.vue'
import CoreProjectCreate from '../src/components/CoreProjectCreate.vue'
import SessionSidebar from '../src/components/SessionSidebar.vue'

describe('CoreProjectCreate', () => {
  it('submits name and path without a Git option', async () => {
    const wrapper = mount(CoreProjectCreate)

    await wrapper.get('[data-project-name]').setValue('Docs')
    await wrapper.get('[data-project-root]').setValue('E:\\docs')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{ name: 'Docs', work_root: 'E:\\docs' }]])
    expect(wrapper.text()).not.toContain('Git')
  })

  it('keeps invalid and loading submissions disabled while exposing errors', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { loading: true, error: '目录不可用' } })

    expect(wrapper.get('[data-project-submit]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[role="alert"]').text()).toBe('目录不可用')

    const idleWrapper = mount(CoreProjectCreate, { props: { error: '目录不可用' } })
    expect(idleWrapper.get('[data-project-submit]').attributes('disabled')).toBeDefined()
    await idleWrapper.get('[data-project-cancel]').trigger('click')

    expect(idleWrapper.emitted('cancel')).toEqual([[]])
  })
})

describe('CoreAgentsEditor', () => {
  it('emits the updated AGENTS.md content and can close without saving', async () => {
    const wrapper = mount(CoreAgentsEditor, { props: { content: '# Existing' } })

    await wrapper.get('[data-agents-content]').setValue('# Updated')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('[data-agents-close]').trigger('click')

    expect(wrapper.emitted('save')).toEqual([['# Updated']])
    expect(wrapper.emitted('close')).toEqual([[]])
  })
})

describe('SessionSidebar compatibility groups', () => {
  it('does not expose project actions for an unassigned compatibility group', () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        allowProjectDelete: true,
        allowProjectClick: true,
        allowProjectContextMenu: true,
        projectGroups: [{
          id: 'unassigned',
          name: 'Unassigned',
          canManage: false,
          sessions: [{ id: 'legacy-1', title: 'Legacy session' }],
        }],
      },
    })

    expect(wrapper.find('.project-action.add').exists()).toBe(false)
    expect(wrapper.find('.project-action.remove').exists()).toBe(false)
    expect(wrapper.find('.project-name').classes()).not.toContain('clickable')
  })
})
