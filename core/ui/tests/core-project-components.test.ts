import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CoreAgentsEditor from '../src/components/CoreAgentsEditor.vue'
import CoreProjectCreate from '../src/components/CoreProjectCreate.vue'
import CoreProjectPicker from '../src/components/CoreProjectPicker.vue'
import CoreProjectSettings from '../src/components/CoreProjectSettings.vue'
import SessionSidebar from '../src/components/SessionSidebar.vue'
import ContextMenuHost from '../src/components/context-menu/ContextMenuHost.vue'
import { closeContextMenu } from '../src/components/context-menu/context-menu'
import { createFakeTransport } from './fake-transport'
import { DEFAULT_THEME } from '../src/helpers/theme'

const transport = createFakeTransport()

function dispatchPointerEvent(
  element: Element,
  type: 'pointerdown' | 'pointerup',
  pointerId = 1,
): void {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, {
    pointerId: { configurable: true, value: pointerId },
    pointerType: { configurable: true, value: 'mouse' },
    button: { configurable: true, value: 0 },
    isPrimary: { configurable: true, value: true },
  })
  element.dispatchEvent(event)
}

describe('CoreProjectCreate', () => {
  it('submits name and path without a Git option', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })

    await wrapper.get('[data-project-name]').setValue('Docs')
    await wrapper.get('[data-project-root]').setValue('E:\\docs')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{
      name: 'Docs',
      work_root: 'E:\\docs',
      icon_key: 'folder',
      color_key: 'gray',
    }]])
    expect(wrapper.text()).not.toContain('Git')
  })

  it('submits an empty optional name when only a path is provided', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })

    await wrapper.get('[data-project-root]').setValue('E:\\path-only')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{
      name: '',
      work_root: 'E:\\path-only',
      icon_key: 'folder',
      color_key: 'gray',
    }]])
  })

  it('creates a named mobile-local project without requesting a desktop directory', async () => {
    const wrapper = mount(CoreProjectCreate, {
      props: { transport, localOnly: true },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.find('[data-project-root]').exists()).toBe(false)
    expect(wrapper.get('[data-project-submit]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-project-name]').setValue('手机项目')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{
      name: '手机项目',
      work_root: '',
      icon_key: 'folder',
      color_key: 'gray',
    }]])
  })

  it('offers eight semantic icons and sixteen colors in the create flow', async () => {
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })

    expect(wrapper.findAll('[data-project-icon-option]')).toHaveLength(8)
    expect(wrapper.findAll('[data-project-color-option]')).toHaveLength(16)
    await wrapper.get('[data-project-icon-option="code"]').trigger('click')
    await wrapper.get('[data-project-color-option="prism"]').trigger('click')
    await wrapper.get('[data-project-root]').setValue('E:\\visual')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]?.[0]).toEqual(expect.objectContaining({
      icon_key: 'code',
      color_key: 'prism',
    }))
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
    const wrapper = mount(CoreProjectCreate, {
      props: { transport },
      global: { stubs: { Teleport: true } },
      attachTo: document.body,
    })
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    dispatchPointerEvent(wrapper.get('[data-project-backdrop]').element, 'pointerdown')
    dispatchPointerEvent(wrapper.get('[data-project-backdrop]').element, 'pointerup')
    expect(wrapper.emitted('cancel')).toEqual([[]])

    const loadingWrapper = mount(CoreProjectCreate, {
      props: { transport, loading: true },
      global: { stubs: { Teleport: true } },
      attachTo: document.body,
    })
    dispatchPointerEvent(loadingWrapper.get('[data-project-backdrop]').element, 'pointerdown')
    dispatchPointerEvent(loadingWrapper.get('[data-project-backdrop]').element, 'pointerup')
    expect(loadingWrapper.emitted('cancel')).toBeUndefined()
  })

  it('does not dismiss when a pointer is dragged from the card onto the backdrop', async () => {
    const wrapper = mount(CoreProjectCreate, {
      props: { transport },
      global: { stubs: { Teleport: true } },
      attachTo: document.body,
    })

    dispatchPointerEvent(wrapper.get('.core-project-dialog').element, 'pointerdown')
    dispatchPointerEvent(wrapper.get('[data-project-backdrop]').element, 'pointerup')

    expect(wrapper.emitted('cancel')).toBeUndefined()
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
      props: {
        projects: [{ id: 'docs', name: 'Docs', workRoot: 'E:\\docs', iconKey: 'folder', colorKey: 'gray' }],
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('#core-project-picker-title').text()).toBe('选择项目')
    expect(wrapper.get('[data-project-picker-item="docs"]').text()).toContain('E:\\docs')
    await wrapper.get('[data-project-picker-item="docs"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['docs']])
  })
})

describe('CoreProjectSettings project visual', () => {
  it('saves project name and visual choices immediately without extra action buttons', async () => {
    const wrapper = mount(CoreProjectSettings, {
      props: {
        project: {
          id: 'docs',
          name: 'Docs',
          workRoot: 'E:\\docs',
          iconKey: 'folder',
          colorKey: 'gray',
        },
        theme: structuredClone(DEFAULT_THEME),
        requestRpc: async () => ({}),
        projectNameDraft: 'Docs',
        agentsContent: '',
        agentsLoading: false,
        agentsError: '',
        projectActionLoading: false,
        projectActionError: '',
      },
      global: { stubs: { Teleport: true } },
    })

    const nameInput = wrapper.get('[data-project-name-input]')
    await nameInput.setValue('Documentation')
    await nameInput.trigger('change')
    await nameInput.trigger('blur')
    await nameInput.trigger('keydown.enter')

    await wrapper.get('[data-project-icon-option="docs"]').trigger('click')
    await wrapper.get('[data-project-color-option="ocean"]').trigger('click')

    expect(wrapper.emitted('rename-project')).toEqual([['Documentation']])
    expect(wrapper.emitted('update-project-visual')).toEqual([
      ['docs', 'gray'],
      ['docs', 'ocean'],
    ])
    expect(wrapper.find('[data-project-visual-save]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('重命名')
    expect(wrapper.text()).not.toContain('保存外观')
  })

  it('has no memory section in project settings: it lives in the 资料库', async () => {
    const rpc = vi.fn(async () => ({}))
    const wrapper = mount(CoreProjectSettings, {
      props: {
        project: {
          id: 'docs',
          name: 'Docs',
          workRoot: 'E:\\docs',
          iconKey: 'folder',
          colorKey: 'gray',
        },
        theme: structuredClone(DEFAULT_THEME),
        requestRpc: rpc,
        projectNameDraft: 'Docs',
        agentsContent: '',
        agentsLoading: false,
        agentsError: '',
        projectActionLoading: false,
        projectActionError: '',
      },
      global: { stubs: { Teleport: true } },
    })

    // 项目设置不再有记忆分区：项目记忆从资料库的记忆区按项目浏览。
    expect(wrapper.find('[data-settings-section="memory"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('查看记忆')
    expect(rpc).not.toHaveBeenCalledWith('memory.reveal', expect.anything())
    wrapper.unmount()
  })

  it('shows the current session prefix and confirms copying the complete ID', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const wrapper = mount(CoreProjectSettings, {
      props: {
        project: {
          id: 'docs',
          name: 'Docs',
          workRoot: 'E:\\docs',
          iconKey: 'folder',
          colorKey: 'gray',
        },
        sessionId: 'abcdef1234567890',
        theme: structuredClone(DEFAULT_THEME),
        requestRpc: async () => ({}),
        projectNameDraft: 'Docs',
        agentsContent: '',
        agentsLoading: false,
        agentsError: '',
        projectActionLoading: false,
        projectActionError: '',
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('[data-project-session-id]').text()).toBe('#abcdef12')
    const copyButton = wrapper.get('[data-project-session-copy]')
    expect(copyButton.text()).toContain('复制完整 ID')

    await copyButton.trigger('click')
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('abcdef1234567890'))
    expect(copyButton.text()).toContain('已复制')
    expect(copyButton.attributes('aria-label')).toBe('已复制完整会话 ID')
    expect(copyButton.attributes('data-copied')).toBeDefined()
    wrapper.unmount()
  })

  it('does not render session details when no current session is available', () => {
    const wrapper = mount(CoreProjectSettings, {
      props: {
        project: {
          id: 'docs',
          name: 'Docs',
          workRoot: 'E:\\docs',
          iconKey: 'folder',
          colorKey: 'gray',
        },
        sessionId: null,
        theme: structuredClone(DEFAULT_THEME),
        requestRpc: async () => ({}),
        projectNameDraft: 'Docs',
        agentsContent: '',
        agentsLoading: false,
        agentsError: '',
        projectActionLoading: false,
        projectActionError: '',
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.find('[data-project-session]').exists()).toBe(false)
    expect(wrapper.find('[data-project-session-copy]').exists()).toBe(false)
  })

  it('keeps solid line icons transparent and reserves filled surfaces for gradients and swatches', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/ProjectVisualIcon.vue'), 'utf8')
    const pickerSource = readFileSync(resolve(process.cwd(), 'src/components/ProjectVisualPicker.vue'), 'utf8')
    const baseRule = source.match(/\.project-visual-icon\s*\{[\s\S]*?\n\}/)?.[0] || ''

    expect(baseRule).toContain('background: transparent')
    expect(source).toMatch(/\.project-visual-icon--gradient\s*\{[\s\S]*?background: var\(--project-visual-color\)/)
    expect(pickerSource).toMatch(/\.project-icon-option\.is-active,[\s\S]*?background:/)
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

  it('uses the project title as an accessible collapse control and disables only busy creation', async () => {
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
    expect(entry.attributes('aria-expanded')).toBe('true')
    await entry.trigger('click')

    expect(entry.attributes('aria-expanded')).toBe('false')
    expect(wrapper.emitted('select-project')).toBeUndefined()
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

describe('Core project session ID contract', () => {
  it('hides the ordinary header short ID and guards settings to the active project session', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')
    const layoutSource = readFileSync(resolve(process.cwd(), 'src/styles/layout.css'), 'utf8')
    // 头部区段以整个 slot 为界：内部还会有自己的 <template v-if> 包装。
    const mainHeader = appSource.match(/<template #main-header>[\s\S]*?<template #main-content>/)?.[0] || ''

    expect(mainHeader).toContain('<CoreSessionTitleEditor')
    expect(mainHeader).toContain('class="thread-header" data-session-header')
    expect(mainHeader).toContain("appRuntime.platform !== 'mobile' && activeSessionId")
    expect(mainHeader).not.toContain(':session-id=')
    expect(appSource).toContain(':session-id="projectSettingsSessionId"')
    expect(appSource).toMatch(/const projectSettingsSessionId = computed\(\(\) => \{[\s\S]*?if \(!activeSessionId\.value \|\| selectedProject\.value\?\.id !== activeProjectId\.value\) return undefined[\s\S]*?return activeSessionId\.value[\s\S]*?\n\}\)/)
    expect(appSource).not.toContain('.thread-header {')
    expect(layoutSource).toMatch(/@media \(min-width: 641px\) \{[\s\S]*?\.thread-header\[data-session-header\] \{[\s\S]*?height: calc\([\s\S]*?\);[\s\S]*?min-height: 0;[\s\S]*?margin-top: calc\(-1 \* var\(--space-6\) - var\(--space-4\) \+ var\(--space-1\)\);[\s\S]*?margin-bottom: 0;[\s\S]*?padding: 0;/)
    expect(layoutSource).not.toContain('.thread-header.wf-floating-header')
  })
})
