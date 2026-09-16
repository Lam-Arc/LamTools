import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RightSidebarHost from '../src/components/RightSidebarHost.vue'
import RightSidebarRag from '../src/components/RightSidebarRag.vue'
import RightSidebarWidgetRenderer from '../src/components/RightSidebarWidgetRenderer.vue'
import {
  listPluginWidgets,
  refreshPluginUIWidgets,
  refreshPluginUIModes,
} from '../src/plugins/api'
import { getWidget, pluginUIRegistry, registerWidget } from '../src/plugins/registry'
import type { PluginWidgetEntry, RightSidebarRpc } from '../src/right-sidebar/types'

describe('RightSidebarHost', () => {
beforeEach(() => localStorage.clear())
afterEach(() => {
  vi.restoreAllMocks()
  pluginUIRegistry.clear()
})

  it('renders the modular first-party stack with Runtime Status collapsed by default', () => {
    const wrapper = mount(RightSidebarHost, { props: { storageKey: 'test.sidebar' } })

    expect(wrapper.find('[data-right-sidebar-host]').exists()).toBe(true)
    expect(wrapper.get('[data-module-id="runtime"]').classes()).toContain('right-sidebar-module--collapsed')
    expect(wrapper.find('[data-module-id="resources"]').exists()).toBe(true)
    expect(wrapper.find('[data-module-id="web-search"]').exists()).toBe(true)
    expect(wrapper.find('[data-module-id="rag"]').exists()).toBe(true)
    expect(wrapper.get('[data-module-id="artifacts"]').classes()).toContain('right-sidebar-module--disabled')

    wrapper.unmount()
  })

  it('keeps motion retained, scoped, and reduced-motion safe', () => {
    const hostSource = readFileSync(resolve(import.meta.dirname, '../src/components/RightSidebarHost.vue'), 'utf8')
    const moduleSource = readFileSync(resolve(import.meta.dirname, '../src/components/RightSidebarModule.vue'), 'utf8')

    expect(hostSource).toContain('<TransitionGroup')
    expect(hostSource).toContain('<Transition name="right-sidebar-mode" mode="out-in">')
    expect(hostSource).toContain('.right-sidebar-mode-enter-active')
    expect(hostSource).toContain('async function animateModuleModeChange()')
    expect(hostSource).toContain("clearProps: 'opacity,transform,visibility,willChange'")
    expect(hostSource).toContain('move-class="right-sidebar-module-list-move"')
    expect(hostSource).toContain('duration: 0.18')
    expect(hostSource).toContain('hostMotionContext?.revert()')
    expect(hostSource).toContain("'(prefers-reduced-motion: reduce)'")
    expect(moduleSource).toContain('v-show="!collapsed"')
    expect(moduleSource).toContain('gridTemplateRows')
    expect(moduleSource).toContain('duration: 0.2')
    expect(moduleSource).toContain("overflow: 'hidden'")
    expect(moduleSource).toContain("clearProps: 'gridTemplateRows,opacity,visibility,overflow,willChange'")
    expect(moduleSource).toMatch(/\.right-sidebar-module-body\s*\{[^}]*overflow: visible;/)
    expect(moduleSource).toMatch(/\.right-sidebar-module-body-content\s*\{[^}]*overflow: visible;/)
    expect(moduleSource).toContain('moduleMotionContext?.revert()')
    expect(moduleSource).toContain("'(prefers-reduced-motion: reduce)'")
  })

  it('persists visibility, collapsed state, and order independently per project', async () => {
    const first = mount(RightSidebarHost, {
      props: { storageKey: 'test.sidebar', projectId: 'project-a' },
    })
    await first.get('.right-sidebar-host-edit').trigger('click')
    const resourcesToggle = first.findAll('.right-sidebar-layout-editor-item input')[1]
    if (!resourcesToggle) throw new Error('resources toggle not rendered')
    await resourcesToggle.setValue(false)
    const runtime = first.get('[data-module-id="runtime"]')
    await runtime.get('.right-sidebar-module-collapse').trigger('click')
    await runtime.get('.right-sidebar-module-move').trigger('click')
    first.unmount()

    const raw = JSON.parse(localStorage.getItem('test.sidebar.right-sidebar') || '{}')
    expect(raw.projects['project-a'].visible.resources).toBe(false)
    expect(raw.projects['project-a'].collapsed.runtime).toBe(false)

    const second = mount(RightSidebarHost, {
      props: { storageKey: 'test.sidebar', projectId: 'project-b' },
    })
    expect(second.find('[data-module-id="resources"]').exists()).toBe(true)
    second.unmount()

    const restored = mount(RightSidebarHost, {
      props: { storageKey: 'test.sidebar', projectId: 'project-a' },
    })
    expect(restored.find('[data-module-id="resources"]').exists()).toBe(false)
    expect(restored.get('[data-module-id="runtime"]').classes()).not.toContain('right-sidebar-module--collapsed')
    restored.unmount()
  })

  it('renders declarative plugin snapshots and never requires raw markup evaluation', () => {
    const entry: PluginWidgetEntry = {
      pluginId: 'example',
      id: 'health',
      title: 'Example Health',
      renderer: 'blocks',
      snapshot: {
        schemaVersion: 1,
        state: 'ok',
        blocks: [
          { type: 'metric', label: 'Jobs', value: 3 },
          { type: 'text', text: '<b>literal</b>' },
        ],
      },
    }
    const wrapper = mount(RightSidebarHost, {
      props: {
        storageKey: 'test.sidebar',
        pluginWidgets: [entry],
      },
    })

    expect(wrapper.get('[data-module-id="plugin:example:health"]').text()).toContain('Jobs')
    expect(wrapper.get('[data-module-id="plugin:example:health"]').text()).toContain('<b>literal</b>')
    expect(wrapper.find('[data-module-id="plugin:example:health"] b').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps the Stage slot as the right-panel mode', () => {
    const wrapper = mount(RightSidebarHost, {
      props: { storageKey: 'test.sidebar', stageOpen: true },
      slots: { stage: '<div data-stage-tree>tree</div>' },
    })
    expect(wrapper.get('[data-right-sidebar-stage]').text()).toContain('tree')
    expect(wrapper.find('[data-right-sidebar-module-list]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps module instances mounted while animating runtime and artifacts mode changes', async () => {
    const wrapper = mount(RightSidebarHost, { props: { storageKey: 'test.sidebar.mode-motion' } })
    const runtimeModule = wrapper.get('[data-module-id="runtime"]').element

    ;(wrapper.vm as unknown as { selectMode: (mode: 'artifacts') => void }).selectMode('artifacts')
    await flushPromises()

    expect(wrapper.get('[data-module-id="runtime"]').element).toBe(runtimeModule)
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain('成果')
    wrapper.unmount()
  })

  it('accepts backend widget discovery and preserves a missing optional facade as a clean state', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'plugin.widget.list') return { widgets: [] }
      return {}
    })
    const wrapper = mount(RightSidebarHost, { props: { requestRpc: rpc } })
    await Promise.resolve()
    expect(wrapper.get('[data-module-id="rag"]').text()).toContain('未安装 RAG 插件')
    expect(rpc).toHaveBeenCalledWith('plugin.widget.list', expect.any(Object))
    wrapper.unmount()
  })

  it('loads session-level sub-agent snapshots and routes source rows to message navigation', async () => {
    const requestRpc = vi.fn(async (method: string) => {
      if (method === 'sub_agent.list') {
        return {
          runs: [{
            id: 'sub-1',
            sub_session_id: 'sub-1',
            name: 'reviewer',
            type: 'execute',
            model: 'model-a',
            reasoning_level: 'medium',
            status: 'running',
            source_message_id: 'parent-1',
            source_part_id: 'agent-1',
            started_at: '2026-07-18T00:00:00.000Z',
          }],
        }
      }
      return {}
    })
    const locateSubAgent = vi.fn()
    const wrapper = mount(RightSidebarHost, {
      props: {
        storageKey: 'test.sidebar.sub-agent',
        sessionId: 'thread-1',
        requestRpc,
        locateSubAgent,
      },
    })

    await flushPromises()
    const row = wrapper.get('[data-module-id="sub-agents"] [data-sub-agent-id="sub-1"]')
    expect(row.text()).toContain('execute')
    expect(row.text()).toContain('运行中')
    expect(row.attributes('title')).toBe('model-a · medium')
    await row.trigger('click')
    expect(locateSubAgent).toHaveBeenCalledWith(expect.objectContaining({
      name: 'reviewer',
      sourceMessageId: 'parent-1',
      sourcePartId: 'agent-1',
    }))
    wrapper.unmount()
  })

  it('gates snapshot fetches on hasSnapshot and watches both operation spellings', async () => {
    const rpcMock = vi.fn(async (method: string) => {
      if (method === 'plugin.widget.get') {
        return { snapshot: { schema_version: 1, state: 'ok', blocks: [] } }
      }
      return {}
    })
    const rpc: RightSidebarRpc = rpcMock
    const entry: PluginWidgetEntry = {
      pluginId: 'example',
      id: 'health',
      title: 'Example Health',
      renderer: 'blocks',
      hasSnapshot: false,
      snapshot_operation: 'example.health.snapshot',
    }
    const wrapper = mount(RightSidebarWidgetRenderer, {
      props: { entry, requestRpc: rpc },
    })

    await flushPromises()
    expect(rpc).not.toHaveBeenCalledWith('plugin.widget.get', expect.anything())

    // Changing only the backend capability bit must trigger a fresh fetch.
    await wrapper.setProps({ entry: { ...entry, hasSnapshot: true } })
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('plugin.widget.get', expect.objectContaining({
      id: 'health',
      plugin_id: 'example',
      widget_id: 'health',
    }))

    const getCalls = rpcMock.mock.calls.filter(([method]) => method === 'plugin.widget.get')
    expect(getCalls).toHaveLength(1)
    wrapper.unmount()

    const camelRpc: RightSidebarRpc = vi.fn(async (method: string) => (
      method === 'plugin.widget.get'
        ? { snapshot: { schema_version: 1, state: 'ok', blocks: [] } }
        : {}
    ))
    const camelWrapper = mount(RightSidebarWidgetRenderer, {
      props: {
        entry: {
          ...entry,
          hasSnapshot: undefined,
          snapshot_operation: undefined,
          snapshotOperation: 'example.health.snapshot',
        },
        requestRpc: camelRpc,
      },
    })
    await flushPromises()
    expect(camelRpc).toHaveBeenCalledWith('plugin.widget.get', expect.any(Object))
    camelWrapper.unmount()

    const snakeRpc: RightSidebarRpc = vi.fn(async (method: string) => (
      method === 'plugin.widget.get'
        ? { snapshot: { schema_version: 1, state: 'ok', blocks: [] } }
        : {}
    ))
    const snakeWrapper = mount(RightSidebarWidgetRenderer, {
      props: {
        entry: {
          ...entry,
          hasSnapshot: undefined,
          snapshotOperation: undefined,
          snapshot_operation: 'example.health.snapshot',
        },
        requestRpc: snakeRpc,
      },
    })
    await flushPromises()
    expect(snakeRpc).toHaveBeenCalledWith('plugin.widget.get', expect.any(Object))
    snakeWrapper.unmount()

    // New backend descriptors advertise the capability without exposing the
    // implementation operation name; the facade still resolves it by id.
    const componentRpc: RightSidebarRpc = vi.fn(async (method: string) => (
      method === 'plugin.widget.get'
        ? { snapshot: { schema_version: 1, state: 'ok', blocks: [] } }
        : {}
    ))
    const componentWrapper = mount(RightSidebarWidgetRenderer, {
      props: {
        entry: {
          pluginId: 'example',
          id: 'component-status',
          title: 'Component Status',
          renderer: 'component',
          hasSnapshot: true,
        },
        requestRpc: componentRpc,
      },
    })
    await flushPromises()
    expect(componentRpc).toHaveBeenCalledWith('plugin.widget.get', expect.objectContaining({
      id: 'component-status',
    }))
    componentWrapper.unmount()
  })

  it('uses descriptor action metadata and only merges snapshot enabled state', async () => {
    const rpc: RightSidebarRpc = vi.fn(async () => ({}))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(RightSidebarWidgetRenderer, {
      props: {
        entry: {
          pluginId: 'example',
          id: 'health',
          title: 'Example Health',
          renderer: 'blocks',
          actions: [{
            id: 'purge',
            title: '清理索引',
            dangerous: true,
            mutates: true,
            inputSchema: { type: 'object' },
          }],
        },
        snapshot: {
          schemaVersion: 1,
          state: 'ok',
          blocks: [],
          actions: [{
            id: 'purge',
            title: '安全检查',
            dangerous: false,
            mutates: false,
            enabled: true,
          } as never, {
            id: 'injected',
            title: '注入操作',
            enabled: true,
          } as never],
        },
        requestRpc: rpc,
      },
    })

    const button = wrapper.get('.right-sidebar-widget-action')
    expect(wrapper.findAll('.right-sidebar-widget-action')).toHaveLength(1)
    expect(button.text()).toBe('清理索引')
    await button.trigger('click')
    expect(confirm).toHaveBeenCalledWith('确定执行「清理索引」？')
    expect(rpc).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('disables snapshot-disabled actions and sends one idempotency key for mutating calls', async () => {
    const rpc: RightSidebarRpc = vi.fn(async () => ({}))
    const wrapper = mount(RightSidebarWidgetRenderer, {
      props: {
        entry: {
          pluginId: 'example',
          id: 'health',
          title: 'Example Health',
          renderer: 'blocks',
          actions: [{ id: 'rebuild', title: '重建索引', mutates: true }],
        },
        snapshot: {
          schemaVersion: 1,
          state: 'ok',
          blocks: [],
          actions: [{ id: 'rebuild', enabled: false } as never],
        },
        requestRpc: rpc,
      },
    })
    const button = wrapper.get('.right-sidebar-widget-action')
    expect(button.attributes('disabled')).toBeDefined()
    await button.trigger('click')
    expect(rpc).not.toHaveBeenCalled()
    wrapper.unmount()

    const activeRpc: RightSidebarRpc = vi.fn(async () => ({}))
    const active = mount(RightSidebarWidgetRenderer, {
      props: {
        entry: {
          pluginId: 'example',
          id: 'health',
          title: 'Example Health',
          renderer: 'blocks',
          actions: [{ id: 'rebuild', title: '重建索引', mutates: true }],
        },
        snapshot: {
          schemaVersion: 1,
          state: 'ok',
          blocks: [],
          actions: [{ id: 'rebuild', enabled: true } as never],
        },
        requestRpc: activeRpc,
      },
    })
    await active.get('.right-sidebar-widget-action').trigger('click')
    await flushPromises()
    expect(activeRpc).toHaveBeenCalledWith('plugin.widget.invoke', {
      id: 'health',
      action: 'rebuild',
      plugin_id: 'example',
      widget_id: 'health',
      action_id: 'rebuild',
      input: {},
      project_id: undefined,
      work_root: undefined,
      session_id: undefined,
      thread_id: undefined,
      confirmed: undefined,
      idempotency_key: expect.any(String),
    })
    active.unmount()
  })

  it('keeps a missing RAG widget explicitly unavailable', async () => {
    const wrapper = mount(RightSidebarRag, {
      props: {
        requestRpc: vi.fn(async () => ({})),
      },
    })
    await flushPromises()
    expect(wrapper.get('.right-sidebar-rag-status').attributes('data-state')).toBe('unavailable')
    expect(wrapper.text()).toContain('未安装 RAG 插件')
    wrapper.unmount()
  })

  it('preserves trusted widget loaders when no bundled loader is available', async () => {
    const trustedLoader = vi.fn(async () => ({ default: {} as never }))
    registerWidget({
      pluginId: 'trusted',
      id: 'status',
      title: 'Trusted Status',
      renderer: 'component',
    }, trustedLoader)
    const requestRpc: RightSidebarRpc = vi.fn(async (method: string) => {
      if (method === 'plugin.widget.list') {
        return { widgets: [{ pluginId: 'trusted', id: 'status', title: 'Trusted Status', renderer: 'blocks' }] }
      }
      if (method === 'plugin.ui.list') {
        return { modes: [], sidebar: { widgets: [{ pluginId: 'trusted', id: 'status', title: 'Trusted Status', renderer: 'blocks' }] } }
      }
      return {}
    })

    await refreshPluginUIWidgets(requestRpc)
    expect(getWidget('status', 'trusted')?.load).toBe(trustedLoader)
    await refreshPluginUIModes(requestRpc)
    expect(getWidget('status', 'trusted')?.load).toBe(trustedLoader)
    expect((await listPluginWidgets(requestRpc)).widgets).toHaveLength(1)
  })
})
