import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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

  it('renders an optional work-root action slot without adding a default browser control', () => {
    const defaultWrapper = mount(CoreProjectCreate)
    const wrapper = mount(CoreProjectCreate, {
      slots: { 'work-root-action': '<button type="button" data-project-browse>浏览</button>' },
    })

    expect(defaultWrapper.find('[data-project-browse]').exists()).toBe(false)
    expect(wrapper.get('[data-project-browse]').text()).toBe('浏览')
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

  it('provides keyboard project management and disables only busy project creation', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        allowProjectClick: true,
        busyProjectIds: ['project-1'],
        projectGroups: [{
          id: 'project-1',
          name: 'Docs',
          workRoot: 'E:\\docs',
          sessions: [{ id: 'session-1', title: 'Write guide' }],
        }],
      },
    })

    const entry = wrapper.get('[data-project-entry="project-1"]')
    const create = wrapper.get('[data-project-new="project-1"]')
    expect(entry.element.tagName).toBe('BUTTON')
    expect(create.attributes('disabled')).toBeDefined()
    await entry.trigger('keydown.enter')
    await entry.trigger('keydown.space')
    await create.trigger('click')

    expect(wrapper.emitted('select-project')).toEqual([['project-1'], ['project-1']])
    expect(wrapper.emitted('new-session')).toBeUndefined()
  })
})

describe('Core project narrow layout contract', () => {
  it('constrains the creation popover to the drawer width without moving it outside the drawer', () => {
    const createSource = readFileSync(resolve(process.cwd(), 'src/components/CoreProjectCreate.vue'), 'utf8')
    const demoSource = readFileSync(resolve(process.cwd(), 'src/demo/App.vue'), 'utf8')

    expect(createSource).toMatch(/\.core-project-create\s*\{[\s\S]*?width:\s*100%;[\s\S]*?min-width:\s*0;/)
    expect(demoSource).toMatch(/\.core-project-create-popover\s*\{[\s\S]*?right:\s*0;[\s\S]*?width:\s*min\(340px,\s*calc\(var\(--left-card-width\)\s*-\s*28px\),\s*calc\(100vw\s*-\s*48px\)\);/)
    expect(demoSource).not.toContain('.core-project-create-popover {\n    right: auto;')
  })
})
