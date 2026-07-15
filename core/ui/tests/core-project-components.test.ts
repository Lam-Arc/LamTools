import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import CoreAgentsEditor from '../src/components/CoreAgentsEditor.vue'
import CoreProjectCreate from '../src/components/CoreProjectCreate.vue'
import SessionSidebar from '../src/components/SessionSidebar.vue'

describe('CoreProjectCreate', () => {
  it('submits name and path without a Git option', async () => {
    const wrapper = mount(CoreProjectCreate, { global: { stubs: { Teleport: true } } })

    await wrapper.get('[data-project-name]').setValue('Docs')
    await wrapper.get('[data-project-root]').setValue('E:\\docs')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{ name: 'Docs', work_root: 'E:\\docs' }]])
    expect(wrapper.text()).not.toContain('Git')
  })

  it('submits an empty optional name when only a path is provided', async () => {
    const wrapper = mount(CoreProjectCreate, { global: { stubs: { Teleport: true } } })

    await wrapper.get('[data-project-root]').setValue('E:\\path-only')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{ name: '', work_root: 'E:\\path-only' }]])
  })

  it('keeps invalid and loading submissions disabled while exposing errors', async () => {
    const wrapper = mount(CoreProjectCreate, {
      props: { loading: true, error: '目录不可用' },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('[data-project-submit]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[role="alert"]').text()).toBe('目录不可用')

    const idleWrapper = mount(CoreProjectCreate, {
      props: { error: '目录不可用' },
      global: { stubs: { Teleport: true } },
    })
    expect(idleWrapper.get('[data-project-submit]').attributes('disabled')).toBeDefined()
    await idleWrapper.get('[data-project-cancel]').trigger('click')

    expect(idleWrapper.emitted('cancel')).toEqual([[]])
  })

  it('owns the directory action and writes the selected path into the shared field', async () => {
    const defaultWrapper = mount(CoreProjectCreate, { global: { stubs: { Teleport: true } } })
    const wrapper = mount(CoreProjectCreate, {
      props: { selectWorkRoot: async () => 'E:\\selected' },
      global: { stubs: { Teleport: true } },
    })

    expect(defaultWrapper.find('[data-project-browse]').exists()).toBe(false)
    await wrapper.get('[data-project-browse]').trigger('click')
    await Promise.resolve()
    expect((wrapper.get('[data-project-root]').element as HTMLInputElement).value).toBe('E:\\selected')
  })

  it('uses a modal backdrop and blocks dismissal while creation is running', async () => {
    const wrapper = mount(CoreProjectCreate, { global: { stubs: { Teleport: true } } })
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    await wrapper.get('[data-project-backdrop]').trigger('mousedown')
    expect(wrapper.emitted('cancel')).toEqual([[]])

    const loadingWrapper = mount(CoreProjectCreate, {
      props: { loading: true },
      global: { stubs: { Teleport: true } },
    })
    await loadingWrapper.get('[data-project-backdrop]').trigger('mousedown')
    expect(loadingWrapper.emitted('cancel')).toBeUndefined()
  })

  it('can cancel the project dialog while the native directory picker is pending', async () => {
    const wrapper = mount(CoreProjectCreate, {
      props: { selectWorkRoot: () => new Promise(() => undefined) },
      global: { stubs: { Teleport: true } },
    })

    await wrapper.get('[data-project-browse]').trigger('click')
    expect(wrapper.get('[data-project-browse]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-project-cancel]').trigger('click')

    expect(wrapper.emitted('cancel')).toEqual([[]])
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
    await wrapper.get('[data-project-menu-trigger="project-1"]').trigger('click')
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
  it('owns a viewport-safe centered dialog instead of a sidebar popover', () => {
    const createSource = readFileSync(resolve(process.cwd(), 'src/components/CoreProjectCreate.vue'), 'utf8')
    const demoSource = readFileSync(resolve(process.cwd(), 'src/demo/App.vue'), 'utf8')

    expect(createSource).toMatch(/<Teleport defer to="\.workspace-shell">/)
    expect(createSource).toMatch(/\.core-project-dialog-backdrop\s*\{[\s\S]*?position:\s*fixed;[\s\S]*?place-items:\s*center;/)
    expect(createSource).toMatch(/\.core-project-dialog\s*\{[\s\S]*?width:\s*min\(520px,\s*100%\);[\s\S]*?max-height:\s*calc\(100dvh\s*-\s*48px\);/)
    expect(demoSource).not.toContain('core-project-create-popover')
  })
})
