import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import CoreAgentsEditor from '../src/components/CoreAgentsEditor.vue'
import CoreProjectCreate from '../src/components/CoreProjectCreate.vue'
import CoreProjectPicker from '../src/components/CoreProjectPicker.vue'
import SessionSidebar from '../src/components/SessionSidebar.vue'
import ContextMenuHost from '../src/components/context-menu/ContextMenuHost.vue'
import { closeContextMenu } from '../src/components/context-menu/context-menu'
import { createFakeTransport } from './fake-transport'

const transport = createFakeTransport()

describe('CoreProjectCreate', () => {
  it('submits name and path without a Git option', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })

    await wrapper.get('[data-project-name]').setValue('Docs')
    await wrapper.get('[data-project-root]').setValue('E:\\docs')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{ name: 'Docs', work_root: 'E:\\docs' }]])
    expect(wrapper.text()).not.toContain('Git')
  })

  it('submits an empty optional name when only a path is provided', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })

    await wrapper.get('[data-project-root]').setValue('E:\\path-only')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{ name: '', work_root: 'E:\\path-only' }]])
  })

  it('reserves this dialog for creating projects', () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })

    expect(wrapper.get('#core-project-dialog-title').text()).toBe('新建项目')
    expect(wrapper.get('[data-project-submit]').text()).toBe('创建项目')
  })

  it('keeps invalid and loading submissions disabled while exposing errors', async () => {
    const wrapper = mount(CoreProjectCreate, {
      props: { transport, loading: true, error: '目录不可用' },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('[data-project-submit]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[role="alert"]').text()).toBe('目录不可用')

    const idleWrapper = mount(CoreProjectCreate, {
      props: { transport, error: '目录不可用' },
      global: { stubs: { Teleport: true } },
    })
    expect(idleWrapper.get('[data-project-submit]').attributes('disabled')).toBeDefined()
    await idleWrapper.get('[data-project-cancel]').trigger('click')

    expect(idleWrapper.emitted('cancel')).toEqual([[]])
  })

  it('owns the directory action and writes the selected path into the shared field', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })

    // The browse button is always available; without a native picker it opens
    // the in-browser folder dialog
    expect(wrapper.find('[data-project-browse]').exists()).toBe(true)
    await wrapper.get('[data-project-browse]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.fb-dialog').exists()).toBe(true)
  })

  it('uses a modal backdrop and blocks dismissal while creation is running', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    await wrapper.get('[data-project-backdrop]').trigger('mousedown')
    expect(wrapper.emitted('cancel')).toEqual([[]])

    const loadingWrapper = mount(CoreProjectCreate, {
      props: { transport, loading: true },
      global: { stubs: { Teleport: true } },
    })
    await loadingWrapper.get('[data-project-backdrop]').trigger('mousedown')
    expect(loadingWrapper.emitted('cancel')).toBeUndefined()
  })

  it('can cancel the project dialog while the directory browser is open', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })

    await wrapper.get('[data-project-browse]').trigger('click')
    await wrapper.get('[data-project-cancel]').trigger('click')

    expect(wrapper.emitted('cancel')).toEqual([[]])
  })
})

describe('CoreProjectPicker', () => {
  it('only offers registered projects for selection', async () => {
    const wrapper = mount(CoreProjectPicker, {
      props: { projects: [{ id: 'docs', name: 'Docs', workRoot: 'E:\\docs' }] },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('#core-project-picker-title').text()).toBe('选择项目')
    expect(wrapper.get('[data-project-picker-item="docs"]').text()).toContain('E:\\docs')
    await wrapper.get('[data-project-picker-item="docs"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['docs']])
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

describe('SessionSidebar project groups', () => {
  let contextMenuHost: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    contextMenuHost = mount(ContextMenuHost, { attachTo: document.body })
  })

  afterEach(() => {
    closeContextMenu()
    contextMenuHost?.unmount()
    contextMenuHost = null
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
    const create = document.body.querySelector<HTMLButtonElement>('[data-project-new="project-1"]')
    expect(entry.element.tagName).toBe('BUTTON')
    expect(create).not.toBeNull()
    expect(create!.disabled).toBe(true)
    await entry.trigger('keydown.enter')
    await entry.trigger('keydown.space')

    expect(wrapper.emitted('select-project')).toEqual([['project-1'], ['project-1']])
    expect(wrapper.emitted('new-session')).toBeUndefined()
  })
})

describe('Core project narrow layout contract', () => {
  it('exposes the existing project creation flow from the sidebar primary area', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')

    expect(appSource).toMatch(/<template #primary>[\s\S]*data-sidebar-primary-action[\s\S]*@click="invokeSidebarPrimaryAction"/)
    expect(appSource).toMatch(/<template #empty>[\s\S]*data-sidebar-empty-projects[\s\S]*sidebar-empty-backdrop[\s\S]*>暂无<\/div>/)
    expect(appSource).not.toContain('data-sidebar-empty-create-project')
    expect(appSource).toContain(':show-sidebar-header="false"')
    expect(appSource).toContain(':show-sidebar-header-action="false"')
    expect(appSource).not.toContain('core-project-header-action')
  })

  it('owns a viewport-safe centered dialog instead of a sidebar popover', () => {
    const createSource = readFileSync(resolve(process.cwd(), 'src/components/CoreProjectCreate.vue'), 'utf8')
    const appSource = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')

    // Mounts to a configurable target (defaults to body) so hosts without a
    // workspace shell still render the dialog (audit 19 S3).
    expect(createSource).toMatch(/<Teleport :to="teleportTarget">/)
    expect(createSource).toMatch(/\.core-project-dialog-backdrop\s*\{[\s\S]*?position:\s*fixed;[\s\S]*?place-items:\s*center;/)
    expect(createSource).toMatch(/\.core-project-dialog\s*\{[\s\S]*?width:\s*min\(520px,\s*100%\);[\s\S]*?max-height:\s*calc\(100dvh\s*-\s*48px\);/)
    expect(appSource).not.toContain('core-project-create-popover')
  })
})
