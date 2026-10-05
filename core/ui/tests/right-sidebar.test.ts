import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RightSidebarHost from '../src/components/RightSidebarHost.vue'
import RightSidebarRag from '../src/components/RightSidebarRag.vue'
import RightSidebarWebSearch from '../src/components/RightSidebarWebSearch.vue'
import UiSelect from '../src/components/UiSelect.vue'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'
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
  vi.useRealTimers()
  // 卡片挂在 body 上：清干净，别让上一例的卡片混进 document 查询。
  document.body.innerHTML = ''
  pluginUIRegistry.clear()
})

  it('shows a low-transmission glass card next to the rail while hovering an icon', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RightSidebarHost, {
      props: { pluginContributions: [{ id: 'surface', title: 'Surface', order: 0 } as never] },
      attachTo: document.body,
    })

    // 竖栏 = 内置模块，一模块一图标，按固定顺序排列；插件/表面条目不入栏。
    const railIds = wrapper.findAll('[data-right-rail-module]').map(b => b.attributes('data-right-rail-module'))
    expect(railIds).toEqual(['runtime', 'resources', 'sub-agents', 'web-search', 'processes', 'rag'])
    // 未悬停时不出卡。
    expect(document.querySelector('[data-right-sidebar-card]')).toBeNull()

    // 悬停图标：左侧浮出对应模块卡（低透玻璃，压住背后的亮色文字）。
    await wrapper.get('[data-right-rail-module="runtime"]').trigger('mouseenter')
    // 卡片挂在 body 上：嵌在带玻璃的抽屉里时，内层模糊采样不到窗外内容。
    const card = new DOMWrapper(document.querySelector('[data-right-sidebar-card]') as HTMLElement)
    expect(card.classes()).toContain('optical-glass')
    expect(card.classes()).toContain('optical-glass--low-trans')
    expect(card.text()).toContain('Runtime Status')

    // 移进卡片保持显示；两侧都离开并越过后，才收起。
    await card.trigger('mouseenter')
    await wrapper.get('[data-right-rail-module="runtime"]').trigger('mouseleave')
    expect(document.querySelector('[data-right-sidebar-card]')).not.toBeNull()
    await card.trigger('mouseleave')
    vi.advanceTimersByTime(1000)
    await wrapper.vm.$nextTick()
    expect(document.querySelector('[data-right-sidebar-card]')).toBeNull()

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('keeps the card alive while the pointer crosses from the rail onto the card', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RightSidebarHost, {
      props: { requestRpc: vi.fn(async () => ({})) },
      attachTo: document.body,
    })
    const rail = wrapper.get('nav.right-sidebar-rail')
    const button = wrapper.get('[data-right-rail-module="processes"]')
    const cardElement = () => document.querySelector('[data-right-sidebar-card]') as HTMLElement | null

    await button.trigger('mouseenter')
    expect(cardElement()).not.toBeNull()

    // 指针离开图标、走进竖栏里图标之间的空白：竖栏整列都是悬停区，卡片不收起。
    await button.trigger('mouseleave')
    vi.advanceTimersByTime(400)
    await wrapper.vm.$nextTick()
    expect(cardElement()).not.toBeNull()

    // 指针走出竖栏、落在竖栏与卡片之间的缝隙里：宽限之内卡片仍然在。
    await rail.trigger('mouseleave')
    vi.advanceTimersByTime(60)
    await wrapper.vm.$nextTick()
    expect(cardElement()).not.toBeNull()

    // 缝隙上的搭桥层接管悬停：停在缝里也不会丢卡，宽限作废。
    const bridge = document.querySelector('[data-right-sidebar-bridge]') as HTMLElement
    expect(bridge).not.toBeNull()
    await new DOMWrapper(bridge).trigger('mouseenter')
    vi.advanceTimersByTime(1000)
    await wrapper.vm.$nextTick()
    expect(cardElement()).not.toBeNull()

    // 指针继续走到卡片上：卡片接管。
    await new DOMWrapper(cardElement() as HTMLElement).trigger('mouseenter')
    vi.advanceTimersByTime(1000)
    await wrapper.vm.$nextTick()
    expect(cardElement()).not.toBeNull()

    // 从卡片离开且不回到竖栏：宽限走完才收起。
    await new DOMWrapper(cardElement() as HTMLElement).trigger('mouseleave')
    vi.advanceTimersByTime(159)
    await wrapper.vm.$nextTick()
    expect(cardElement()).not.toBeNull()
    vi.advanceTimersByTime(1)
    await wrapper.vm.$nextTick()
    expect(cardElement()).toBeNull()

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('reports the occupied right-rail area to the shell while the card is out', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RightSidebarHost, {
      props: { requestRpc: vi.fn(async () => ({})) },
      attachTo: document.body,
    })

    expect(wrapper.emitted('hover-change')).toBeUndefined()
    await wrapper.get('[data-right-rail-module="rag"]').trigger('mouseenter')
    expect(wrapper.emitted('hover-change')?.at(-1)).toEqual([true])

    // 卡片收起的同时交还区域，壳层才知道可以跟着收竖栏。
    await wrapper.get('nav.right-sidebar-rail').trigger('mouseleave')
    vi.advanceTimersByTime(1000)
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('hover-change')?.at(-1)).toEqual([false])

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('keeps the hover card content-sized with a large radius and motion fallbacks', () => {
    const hostSource = readFileSync(resolve(import.meta.dirname, '../src/components/RightSidebarHost.vue'), 'utf8')

    expect(hostSource).toContain('class="right-sidebar-card optical-glass optical-glass--low-trans"')
    // 卡片头已带模块名：面板内部同名标题在卡内隐藏，避免重复。
    expect(hostSource).toMatch(/\.right-sidebar-card-body :deep\(\.runtime-widget-head h3\)\s*\{[^}]*display: none;/)
    // 大圆角 + 只设尺寸上限（可小于、不可大于）。
    expect(hostSource).toMatch(/\.right-sidebar-card\s*\{[^}]*border-radius: var\(--radius-lg\);/)
    expect(hostSource).toMatch(/\.right-sidebar-card\s*\{[^}]*width: 285px;[^}]*max-height: 505px;/)
    // 缝隙上铺一条不可见的搭桥层：右端压住卡片边缘、左端压进竖栏内缘。
    // 它必须与卡片同级——玻璃面 overflow: hidden，挂在卡片内部会被裁掉；
    // 也不能复用 ::after，那是玻璃材质的折射层且 pointer-events: none。
    expect(hostSource).toContain('class="right-sidebar-card-bridge"')
    expect(hostSource).toMatch(/\.right-sidebar-card-bridge\s*\{[^}]*right: calc\(var\(--right-rail-width, 46px\) - 2px\);[^}]*width: calc\(var\(--space-2\) \+ 4px\);/)
    expect(hostSource).not.toMatch(/\.right-sidebar-card::after/)
    // 入场只做透明度淡入，且带减弱动态效果回退。
    expect(hostSource).toMatch(/@keyframes right-card-in\s*\{[^}]*opacity/)
    expect(hostSource).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?right-sidebar-card \{ animation: none; \}/)
  })

  it('loads module data only when its card opens', async () => {
    const rpc = vi.fn(async () => ({}))
    const wrapper = mount(RightSidebarHost, { props: { requestRpc: rpc } })
    await flushPromises()
    expect(rpc).not.toHaveBeenCalled()

    await wrapper.get('[data-right-rail-module="web-search"]').trigger('mouseenter')
    await flushPromises()
    expect(rpc).toHaveBeenCalled()
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
    // 危险动作先问一次：应用内确认框，未确认不动手。
    await button.trigger('click')
    const dialog = wrapper.getComponent(CoreConfirmDialog)
    expect(dialog.props('open')).toBe(true)
    expect(dialog.props('title')).toBe('清理索引')
    expect(rpc).not.toHaveBeenCalled()

    // 取消就不执行；确认才执行。
    dialog.vm.$emit('cancel')
    await flushPromises()
    expect(rpc).not.toHaveBeenCalled()
    await button.trigger('click')
    wrapper.getComponent(CoreConfirmDialog).vm.$emit('confirm')
    await flushPromises()
    expect(rpc).toHaveBeenCalled()
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

describe('RightSidebarWebSearch plugin state', () => {
  it('shows the disabled hint while the websearch plugin is off, and recovers after recheck', async () => {
    const disabledRpc: RightSidebarRpc = vi.fn(async (method: string) => {
      if (method === 'websearch.config.get') return { content: '{"provider": "bing"}' }
      // 插件被禁用时它的操作整体不存在——宿主返回"方法不存在"。
      throw new Error('Unsupported method: websearch.widget.snapshot')
    })
    const wrapper = mount(RightSidebarWebSearch, { props: { requestRpc: disabledRpc } })
    await flushPromises()

    expect(wrapper.text()).toContain('搜索插件未启用')
    expect(wrapper.findComponent(UiSelect).exists()).toBe(false)

    const enabledRpc: RightSidebarRpc = vi.fn(async (method: string) => {
      if (method === 'websearch.config.get') return { content: '{"provider": "bing"}' }
      return { snapshot: { schema_version: 1, state: 'ok', summary: 'Configured engine: bing', blocks: [] } }
    })
    await wrapper.setProps({ requestRpc: enabledRpc })
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('搜索插件未启用')
    expect(wrapper.findComponent(UiSelect).exists()).toBe(true)

    wrapper.unmount()
  })
})
