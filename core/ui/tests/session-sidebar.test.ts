import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SessionSidebar from '../src/components/SessionSidebar.vue'
import ContextMenuHost from '../src/components/context-menu/ContextMenuHost.vue'
import { closeContextMenu } from '../src/components/context-menu/context-menu'

const groups = [
  {
    id: 'recent-new',
    name: 'Recent new',
    sessions: [{ id: 's1', title: 'One', updatedAt: '2026-07-12T08:00:00Z' }],
  },
  {
    id: 'recent-old',
    name: 'Recent old',
    sessions: [{ id: 's2', title: 'Two', createdAt: '2026-07-01T08:00:00Z' }],
  },
  {
    id: 'earlier',
    name: 'Earlier',
    sessions: [{ id: 's3', title: 'Three', updatedAt: '2026-05-01T08:00:00Z' }],
  },
]

async function openSessionMenu(wrapper: ReturnType<typeof mount>, sessionId: string) {
  await wrapper.get(`[data-session-row="${sessionId}"]`).trigger('contextmenu', {
    clientX: 120,
    clientY: 80,
  })
  await nextTick()
  const menus = document.body.querySelectorAll<HTMLElement>(`[data-session-menu="${sessionId}"]`)
  const menu = menus[menus.length - 1]
  expect(menu).not.toBeNull()
  return menu!
}

function dispatchClick(element: Element): void {
  ;(element as HTMLElement).click()
}

describe('SessionSidebar sections', () => {
  let contextMenuHost: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    document.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    localStorage.clear()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-13T08:00:00Z'))
    contextMenuHost = mount(ContextMenuHost, { attachTo: document.body })
  })

  afterEach(() => {
    closeContextMenu()
    contextMenuHost?.unmount()
    contextMenuHost = null
    vi.useRealTimers()
  })

  it('groups unpinned projects by activity and sorts newest first', () => {
    const wrapper = mount(SessionSidebar, { props: { projectGroups: groups } })

    const section = wrapper.get('[data-sidebar-section="default"]')
    expect(section.findAll('.project-block').map((node) => node.text()))
      .toEqual([
        expect.stringContaining('Recent new'),
        expect.stringContaining('Recent old'),
        expect.stringContaining('Earlier'),
      ])
    expect(wrapper.find('[data-sidebar-section="pinned"]').exists()).toBe(false)
  })

  it('labels the default project section without adding panel chrome', () => {
    const wrapper = mount(SessionSidebar, { props: { projectGroups: groups } })
    expect(wrapper.get('[data-sidebar-section="default"] .sidebar-section-title').text()).toBe('项目')

    const css = readFileSync(resolve(import.meta.dirname, '../src/styles/session-sidebar.css'), 'utf8')
    const titleRule = css.match(/\.sidebar-section-title \{([\s\S]*?)\}/)?.[1] || ''
    expect(titleRule).toContain('font-weight: 500;')
    expect(titleRule).not.toContain('background')
    expect(titleRule).not.toContain('border')
  })

  it('renders the 最近 section as a flat cross-project list', () => {
    const wrapper = mount(SessionSidebar, { props: { projectGroups: groups } })
    const recent = wrapper.get('[data-sidebar-section="recent"]')
    expect(recent.text()).toContain('最近')
    expect(recent.findAll('[data-sidebar-recent-row]').length).toBeGreaterThan(0)
    // 平铺行里带项目名做来源提示。
    expect(recent.get('[data-sidebar-recent-row]').text()).toContain(groups[0].name)
  })

  it('folds a section fully and expands it fully from the section-head icon', async () => {
    const many = Array.from({ length: 6 }, (_value, index) => ({
      id: `p${index}`,
      name: `项目 ${index}`,
      sessions: [{ id: `s${index}`, title: `会话 ${index}` }],
    }))
    const wrapper = mount(SessionSidebar, { props: { projectGroups: many } })
    const section = wrapper.get('[data-sidebar-section="default"]')
    // 默认完全展开：全部项目都在。
    expect(section.findAll('[data-project-row]')).toHaveLength(6)

    const toggle = wrapper.get('[data-sidebar-section-more="default"]')
    expect(toggle.find('svg').exists()).toBe(true)
    expect(toggle.attributes('aria-expanded')).toBe('true')

    // 完全折叠：一条不留。
    await toggle.trigger('click')
    expect(section.findAll('[data-project-row]')).toHaveLength(0)
    expect(toggle.attributes('aria-expanded')).toBe('false')

    // 再点恢复完全展开。
    await toggle.trigger('click')
    expect(section.findAll('[data-project-row]')).toHaveLength(6)
    expect(toggle.attributes('aria-expanded')).toBe('true')
  })

  it('caps the expanded 最近 list at twelve entries and folds it fully', async () => {
    const sixteen = Array.from({ length: 16 }, (_value, index) => ({
      id: `r${index}`,
      name: `最近项目 ${index}`,
      sessions: [{ id: `rs${index}`, title: `最近会话 ${index}`, updatedAt: `2026-07-${String(index + 1).padStart(2, '0')}T08:00:00Z` }],
    }))
    const wrapper = mount(SessionSidebar, { props: { projectGroups: sixteen } })
    const recent = wrapper.get('[data-sidebar-section="recent"]')
    // 完全展开档最多 12 条。
    expect(recent.findAll('[data-sidebar-recent-row]')).toHaveLength(12)

    const toggle = recent.get('[data-sidebar-recent-toggle]')
    expect(toggle.attributes('aria-expanded')).toBe('true')

    // 完全折叠：一条不留。
    await toggle.trigger('click')
    expect(wrapper.get('[data-sidebar-section="recent"]').findAll('[data-sidebar-recent-row]')).toHaveLength(0)
    expect(toggle.attributes('aria-expanded')).toBe('false')
  })

  it('keeps project rows limited to the project name', () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: [{
          id: 'docs',
          name: 'Docs',
          workRoot: 'E:\\docs',
          sessions: [{ id: 'session-1', title: 'Guide' }],
        }],
      },
    })

    const project = wrapper.get('[data-project-entry="docs"]')
    expect(project.text().trim()).toBe('Docs')
    expect(project.find('.work-root').exists()).toBe(false)
    expect(project.text()).not.toContain('E:\\docs')
  })

  it('keeps search as a compact icon until it is focused or opened', async () => {
    const wrapper = mount(SessionSidebar, { props: { projectGroups: groups, localFilter: true } })
    const searchWrap = wrapper.get('.sidebar-search-wrap')
    const searchToggle = wrapper.get('[data-sidebar-search-toggle]')

    expect(searchToggle.find('svg').exists()).toBe(true)
    expect(searchWrap.classes()).not.toContain('is-expanded')
    expect(searchToggle.attributes('aria-expanded')).toBe('false')

    await searchToggle.trigger('click')
    expect(searchWrap.classes()).toContain('is-expanded')
    expect(searchToggle.attributes('aria-expanded')).toBe('true')
  })

  it('filters project and session names locally without changing source groups', async () => {
    const wrapper = mount(SessionSidebar, { props: { projectGroups: groups, localFilter: true } })
    const input = wrapper.get('[data-sidebar-search]')

    await input.setValue('  RECENT NEW ')
    expect(wrapper.findAll('.project-block')).toHaveLength(1)
    expect(wrapper.get('.project-block').text()).toContain('Recent new')

    await input.setValue('two')
    expect(wrapper.findAll('.project-block')).toHaveLength(1)
    expect(wrapper.get('.project-block').text()).toContain('Two')
    expect(wrapper.find('[data-session-row="s1"]').exists()).toBe(false)
    expect(groups[0].sessions).toHaveLength(1)
    expect(groups[1].sessions).toHaveLength(1)

    await input.setValue('no matching item')
    expect(wrapper.find('.project-block').exists()).toBe(false)
    expect(wrapper.get('[data-sidebar-search-empty]').text()).toContain('未找到匹配的项目或会话')
    expect(wrapper.get('[data-sidebar-search-clear]').text()).toContain('清除搜索')

    await wrapper.get('[data-sidebar-search-clear]').trigger('click')
    expect(wrapper.find('[data-sidebar-search-empty]').exists()).toBe(false)
    expect(wrapper.findAll('.project-block')).toHaveLength(3)
  })

  it('temporarily expands matching projects and restores their collapse state', async () => {
    const searchGroups = [
      {
        id: 'alpha',
        name: 'Alpha',
        sessions: [
          { id: 'alpha-1', title: 'Alpha session' },
          { id: 'alpha-2', title: 'Another alpha session' },
        ],
      },
      {
        id: 'beta',
        name: 'Beta',
        sessions: [{ id: 'beta-1', title: 'Needle session' }],
      },
    ]
    const wrapper = mount(SessionSidebar, {
      props: { projectGroups: searchGroups, pinStorageKey: 'search-collapse', localFilter: true },
    })

    const betaEntry = wrapper.get('[data-project-entry="beta"]')
    await betaEntry.trigger('click')
    expect(betaEntry.attributes('aria-expanded')).toBe('false')

    await wrapper.get('[data-sidebar-search]').setValue('needle')
    expect(wrapper.find('[data-project-entry="beta"]').exists()).toBe(true)
    expect(betaEntry.attributes('aria-expanded')).toBe('true')

    await wrapper.get('[data-sidebar-search]').setValue('')
    expect(betaEntry.attributes('aria-expanded')).toBe('false')

    await wrapper.get('[data-sidebar-search]').setValue('alpha')
    expect(wrapper.findAll('[data-session-row^="alpha-"]')).toHaveLength(2)
  })

  it('explains an expanded project with no sessions and reuses the new-session event', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: [{ id: 'empty', name: 'Empty project', sessions: [] }],
      },
    })

    expect(wrapper.get('[data-project-empty]').text()).toContain('暂无会话')
    await wrapper.get('[data-project-empty-new="empty"]').trigger('click')
    expect(wrapper.emitted('new-session')).toEqual([['empty']])

    await wrapper.get('[data-project-entry="empty"]').trigger('click')
    expect(wrapper.find('[data-project-empty]').isVisible()).toBe(false)
  })

  it('uses the explicit project boundary when a host reports no projects', () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        hasProjects: false,
        projectGroups: [{
          id: 'internal',
          name: 'Internal',
          canManage: false,
          sessions: [{ id: 'legacy-1', title: 'Legacy session', createdAt: '2026-07-12T08:00:00Z' }],
        }],
      },
      slots: { empty: '<div data-explicit-empty>还没有项目</div>' },
    })

    expect(wrapper.get('[data-explicit-empty]').text()).toBe('还没有项目')
    expect(wrapper.find('[data-sidebar-search]').exists()).toBe(false)
    expect(wrapper.find('.project-block').exists()).toBe(false)
  })

  it('pins projects durably and restores them in the pinned section', async () => {
    const wrapper = mount(SessionSidebar, {
      props: { projectGroups: groups, pinStorageKey: 'test.sidebar.pins' },
    })

    await wrapper.get('[data-project-menu-trigger="earlier"]').trigger('click')
    document.body.querySelector<HTMLElement>('[data-project-pin="earlier"]')!.click()
    await nextTick()

    expect(wrapper.get('[data-sidebar-section="pinned"]').text()).toContain('Earlier')
    expect(localStorage.getItem('test.sidebar.pins')).toBe('["earlier"]')

    const restored = mount(SessionSidebar, {
      props: { projectGroups: groups, pinStorageKey: 'test.sidebar.pins' },
    })
    expect(restored.get('[data-sidebar-section="pinned"]').text()).toContain('Earlier')

    await restored.get('[data-project-menu-trigger="earlier"]').trigger('click')
    document.body.querySelector<HTMLElement>('[data-project-pin="earlier"]')!.click()
    await nextTick()
    expect(restored.find('[data-sidebar-section="pinned"]').exists()).toBe(false)
    expect(restored.get('[data-sidebar-section="default"]').text()).toContain('Earlier')
  })

  it('opens a restrained project menu with project actions', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowProjectDelete: true,
        allowProjectContextMenu: true,
      },
      attachTo: document.body,
    })

    await wrapper.get('[data-project-menu-trigger="recent-new"]').trigger('click')

    const menu = document.body.querySelector<HTMLElement>('[data-project-menu="recent-new"]')
    expect(menu).not.toBeNull()
    expect(menu!.getAttribute('role')).toBe('menu')
    expect(menu!.textContent).toContain('新建会话')
    expect(menu!.textContent).toContain('置顶项目')
    expect(menu!.textContent).toContain('项目设置')
    expect(menu!.textContent).toContain('删除项目')
  })

  it('can omit desktop-only project settings while retaining mobile actions', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowProjectContextMenu: true,
        allowProjectDelete: true,
        allowProjectSettings: false,
      },
      attachTo: document.body,
    })

    await wrapper.get('[data-project-menu-trigger="recent-new"]').trigger('click')
    const menu = document.body.querySelector<HTMLElement>('[data-project-menu="recent-new"]')
    expect(menu?.textContent).toContain('重命名')
    expect(menu?.textContent).toContain('删除项目')
    expect(menu?.textContent).not.toContain('项目设置')
  })

  it('keeps the project row to name and menu without a fold chevron', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowProjectClick: true,
      },
    })

    const row = wrapper.get('[data-project-entry="recent-new"]').element.parentElement!
    expect(row.classList.contains('project-row')).toBe(true)
    expect(row.querySelector('.project-toggle')).toBeNull()
    expect(row.querySelector('.project-main')).not.toBeNull()
    expect(row.querySelector('.project-menu-button')).not.toBeNull()
    expect(row.querySelector('.project-main button')).toBeNull()

    await wrapper.get('[data-project-menu-trigger="recent-new"]').trigger('click')
    expect(document.body.querySelector('[data-project-menu="recent-new"]')).not.toBeNull()
    expect(wrapper.get('[data-project-entry="recent-new"]').attributes('aria-expanded')).toBe('true')
  })

  it('opens only the clicked project menu when a project is projected in both sections', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        pinStorageKey: 'test.sidebar.pins',
      },
    })

    const menu = await openSessionMenu(wrapper, 's1')
    dispatchClick(menu.querySelector('[data-session-menu-pin="s1"]')!)
    await nextTick()

    const triggers = wrapper.findAll('[data-project-menu-trigger="recent-new"]')
    expect(triggers).toHaveLength(2)

    await triggers[0].trigger('click')
    expect(document.body.querySelectorAll('[data-project-menu="recent-new"]')).toHaveLength(1)
    expect(triggers[0].attributes('aria-expanded')).toBe('true')
    expect(triggers[1].attributes('aria-expanded')).toBe('false')

    await triggers[1].trigger('click')
    expect(document.body.querySelectorAll('[data-project-menu="recent-new"]')).toHaveLength(1)
    expect(triggers[0].attributes('aria-expanded')).toBe('false')
    expect(triggers[1].attributes('aria-expanded')).toBe('true')
  })

  it('keeps the menu mounted through pointerdown and dispatches every project action', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowProjectDelete: true,
        allowProjectContextMenu: true,
      },
      attachTo: document.body,
    })

    for (const [selector, event] of [
      ['[data-project-new="recent-new"]', 'new-session'],
      ['[data-project-pin="recent-new"]', null],
      ['[data-project-rename="recent-new"]', 'rename-project'],
      ['[data-project-menu="recent-new"] button:nth-last-of-type(2)', 'project-context-menu'],
      ['[data-project-menu="recent-new"] button:last-of-type', 'delete-project'],
    ] as const) {
      await wrapper.get('[data-project-menu-trigger="recent-new"]').trigger('click')
      const action = document.body.querySelector<HTMLElement>(selector)
      expect(action).not.toBeNull()
      action!.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
      expect(document.body.querySelector('[data-project-menu="recent-new"]')).not.toBeNull()
      action!.click()
      await nextTick()
      if (event) expect(wrapper.emitted(event)?.at(-1)).toEqual(['recent-new'])
    }
  })

  it('suppresses the browser menu when a plugin disables project or session actions', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowProjectContextMenu: false,
        allowSessionContextMenu: false,
      },
    })

    const projectEvent = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    const sessionEvent = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    wrapper.get('[data-project-entry="recent-new"]').element.dispatchEvent(projectEvent)
    wrapper.get('[data-session-row="s1"]').element.dispatchEvent(sessionEvent)

    expect(projectEvent.defaultPrevented).toBe(true)
    expect(sessionEvent.defaultPrevented).toBe(true)
    expect(document.body.querySelector('[data-project-menu="recent-new"]')).toBeNull()
    expect(document.body.querySelector('[data-session-menu="s1"]')).toBeNull()
  })

  it('selects a session when its title text is clicked', async () => {
    const wrapper = mount(SessionSidebar, { props: { projectGroups: groups } })

    const row = wrapper.get('[data-session-row="s1"]')
    expect(row.classes()).toContain('session-row')
    expect(row.get('.session-main').classes()).toContain('session-main')
    expect(row.get('.session-title').text()).toBe('One')

    await row.get('.session-title').trigger('click')

    expect(wrapper.emitted('select-session')).toEqual([['s1']])
    expect(wrapper.find('.session-name-input').exists()).toBe(false)
  })

  it('truncates long session names by available width and keeps the full title in the action menu', async () => {
    const title = '调查输入框权限切换改动画面'
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: [{ id: 'project', name: 'Project', sessions: [{ id: 'long', title }] }],
      },
      attachTo: document.body,
    })

    expect(wrapper.get('[data-session-row="long"] .session-title').text()).toBe(title)

    const css = readFileSync(resolve(import.meta.dirname, '../src/styles/session-sidebar.css'), 'utf8')
    const selectRule = css.match(/\.conversation-select \{([\s\S]*?)\n\}/)?.[1] || ''
    expect(selectRule).toContain('flex: 1 1 auto;')
    expect(selectRule).toContain('width: 0;')
    expect(selectRule).toContain('min-width: 0;')
    expect(selectRule).not.toContain('width: 100%;')
    expect(css).toMatch(/\.conversation-main \{[\s\S]*?flex: 1 1 auto;[\s\S]*?width: 0;[\s\S]*?overflow: hidden;/)
    expect(css).toMatch(/\.session-title \{[\s\S]*?width: 100%;[\s\S]*?overflow: hidden;[\s\S]*?text-overflow: ellipsis;/)

    await wrapper.get('[data-session-row="long"]').trigger('contextmenu', { clientX: 120, clientY: 80 })
    await nextTick()
    expect(document.querySelector('[data-session-menu="long"]')?.getAttribute('aria-label')).toBe('调查输入框权限切换改动画面 会话操作')
  })

  it('keeps project rows transparent while sessions retain row states', () => {
    const css = readFileSync(resolve(import.meta.dirname, '../src/styles/session-sidebar.css'), 'utf8')

    expect(css).toMatch(/\.project-row,[\s\S]*?\.session-row \{[\s\S]*?background: transparent;/)
    expect(css).not.toMatch(/\.project-row:hover\s*\{[\s\S]*?background:/)
    expect(css).not.toMatch(/\.project-block\.active\s*\{[\s\S]*?background:/)
    expect(css).toMatch(/\.conversation\.active::before \{[\s\S]*?linear-gradient\([\s\S]*?var\(--sidebar-selected-fill\)/)
    expect(css).toMatch(/\.conversation strong \{[\s\S]*?font-weight: 400;/)
    expect(css).toMatch(/\.project-name strong \{[\s\S]*?font-size: var\(--sidebar-text-size\);/)
    expect(css).toMatch(/\.conversation strong \{[\s\S]*?font-size: var\(--sidebar-text-size\);/)
    expect(css).not.toMatch(/\.session-row\.is-active \.session-title\s*\{[\s\S]*?font-weight:/)
    expect(css).toMatch(/\.sidebar-sort-move\s*\{[\s\S]*?transition: transform var\(--dur-base\) var\(--ease-out\);/)
    expect(css).toMatch(/\.project-row\.is-dragging,[\s\S]*?\.conversation\.is-dragging\s*\{[\s\S]*?opacity: 1;/)
    expect(css).not.toMatch(/\.is-drag-over::after/)
  })

  it('keeps project and session actions quiet until their row is active', () => {
    const css = readFileSync(resolve(import.meta.dirname, '../src/styles/session-sidebar.css'), 'utf8')

    expect(css).toMatch(/\.project-btns \{[\s\S]*?position: absolute;[\s\S]*?opacity: 0;[\s\S]*?pointer-events: none;/)
    // 「···」是行内浮层：不占项目名的布局空间（不得回到 flex 占位）。
    expect(css).not.toMatch(/\.project-btns \{[^}]*flex: 0 0 28px/)
    expect(css).toMatch(/\.project-block:hover \.project-btns,[\s\S]*?\.project-btns:has\(\.project-menu-button\[aria-expanded="true"\]\)/)
    expect(css).not.toContain('.conversation-hover-actions')
    expect(css).not.toContain('.session-context-menu')
    expect(css).not.toContain('.session-export-menu')
    const contextMenuCss = readFileSync(resolve(import.meta.dirname, '../src/components/context-menu/ContextMenuPanel.vue'), 'utf8')
    expect(contextMenuCss).toMatch(/\.context-menu-panel\s*\{[\s\S]*?position: fixed;[\s\S]*?z-index: var\(--z-popover/)
  })

  it('uses a transparent native drag image while sorting', async () => {
    const wrapper = mount(SessionSidebar, { props: { projectGroups: groups } })
    const dataTransfer = {
      effectAllowed: '',
      setData: vi.fn(),
      setDragImage: vi.fn(),
    } as unknown as DataTransfer

    await wrapper.get('[data-session-row="s1"]').trigger('dragstart', { dataTransfer })

    expect(dataTransfer.setDragImage).toHaveBeenCalledWith(
      wrapper.get('.sidebar-drag-image').element,
      0,
      0,
    )
  })

  it('keeps keyboard focus visible for session controls', () => {
    const sidebarCss = readFileSync(resolve(import.meta.dirname, '../src/styles/session-sidebar.css'), 'utf8')
    const shellCss = readFileSync(resolve(import.meta.dirname, '../src/styles/workspace-shell.css'), 'utf8')

    expect(shellCss).toMatch(/\.sidebar-root :focus-visible \{[\s\S]*?outline: 2px solid/)
    expect(sidebarCss).not.toMatch(/\.conversation-select:focus-visible \{[\s\S]*?outline:\s*none/)
    expect(sidebarCss).not.toMatch(/\.conversation-action:hover,[\s\S]*?\.conversation-action:focus-visible \{[\s\S]*?outline:\s*none/)
  })

  it('pins a session into a project-only pinned projection without reordering the source project', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        pinStorageKey: 'test.sidebar.pins',
        allowSessionDelete: true,
        projectGroups: [{
          id: 'project',
          name: 'Project',
          sessions: [
            { id: 'older', title: 'Older', createdAt: '2026-07-01T08:00:00Z' },
            { id: 'newer', title: 'Newer', createdAt: '2026-07-12T08:00:00Z', status: 'running' },
          ],
        }],
      },
    })

    const menu = await openSessionMenu(wrapper, 'newer')
    dispatchClick(menu.querySelector('[data-session-menu-pin="newer"]')!)
    await nextTick()

    const pinned = wrapper.get('[data-sidebar-section="pinned"]')
    expect(pinned.findAll('[data-project-entry="project"]')).toHaveLength(1)
    expect(pinned.findAll('[data-session-row]')).toHaveLength(1)
    expect(pinned.find('[data-session-row="newer"] .status.conversation-status.running').exists()).toBe(true)

    const original = wrapper.get('[data-sidebar-section="default"]')
    expect(original.findAll('[data-session-row]').map((row) => row.attributes('data-session-row')))
      .toEqual(['older'])
    expect(localStorage.getItem('test.sidebar.pins.sessions')).toBe('["newer"]')
    expect(pinned.get('[data-session-row="newer"]')).toBeTruthy()
  })

  it('shows newly created sessions at the top', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        pinStorageKey: 'test.sidebar.newest-first',
        projectGroups: [{
          id: 'project',
          name: 'Project',
          sessions: [
            { id: 'older', title: 'Older', createdAt: '2026-07-01T08:00:00Z' },
            { id: 'newer', title: 'Newer', createdAt: '2026-07-12T08:00:00Z' },
          ],
        }],
      },
    })

    expect(wrapper.findAll('[data-sidebar-section="default"] [data-session-row]').map(row => row.attributes('data-session-row')))
      .toEqual(['newer', 'older'])

    await wrapper.setProps({
      projectGroups: [{
        id: 'project',
        name: 'Project',
        sessions: [
          { id: 'older', title: 'Older', createdAt: '2026-07-01T08:00:00Z' },
          { id: 'newer', title: 'Newer', createdAt: '2026-07-12T08:00:00Z' },
          { id: 'newest', title: 'Newest', createdAt: '2026-07-20T08:00:00Z' },
        ],
      }],
    })

    expect(wrapper.findAll('[data-sidebar-section="default"] [data-session-row]').map(row => row.attributes('data-session-row')))
      .toEqual(['newest', 'newer', 'older'])
  })

  it('reorders projects and sessions by drag and persists both orders', async () => {
    const projectGroups = [
      { id: 'project-a', name: 'Project A', sessions: [{ id: 'a-1', title: 'A1' }] },
      {
        id: 'project-b',
        name: 'Project B',
        sessions: [
          { id: 'b-1', title: 'B1' },
          { id: 'b-2', title: 'B2' },
          { id: 'b-3', title: 'B3' },
        ],
      },
      { id: 'project-c', name: 'Project C', sessions: [{ id: 'c-1', title: 'C1' }] },
    ]
    const wrapper = mount(SessionSidebar, {
      props: { projectGroups, pinStorageKey: 'test.sidebar.order' },
    })

    const projectTarget = wrapper.get('[data-project-row="project-a"]')
    vi.spyOn(projectTarget.element, 'getBoundingClientRect').mockReturnValue({ top: 0, height: 100 } as DOMRect)
    await wrapper.get('[data-project-row="project-c"]').trigger('dragstart')
    await projectTarget.trigger('dragover', { clientY: 20 })
    expect(wrapper.findAll('[data-sidebar-section="default"] [data-project-row]')
      .map((row) => row.attributes('data-project-row')))
      .toEqual(['project-c', 'project-a', 'project-b'])
    await projectTarget.trigger('drop')
    expect(wrapper.findAll('[data-sidebar-section="default"] [data-project-row]')
      .map((row) => row.attributes('data-project-row')))
      .toEqual(['project-c', 'project-a', 'project-b'])

    const sessionTarget = wrapper.get('[data-session-row="b-1"]')
    vi.spyOn(sessionTarget.element, 'getBoundingClientRect').mockReturnValue({ top: 0, height: 100 } as DOMRect)
    await wrapper.get('[data-session-row="b-3"]').trigger('dragstart')
    await sessionTarget.trigger('dragover', { clientY: 20 })
    expect(wrapper.findAll('[data-sidebar-section="default"] [data-session-row]')
      .map((row) => row.attributes('data-session-row')))
      .toEqual(['c-1', 'a-1', 'b-3', 'b-1', 'b-2'])
    await sessionTarget.trigger('drop')
    expect(wrapper.findAll('[data-sidebar-section="default"] [data-session-row]')
      .map((row) => row.attributes('data-session-row')))
      .toEqual(['c-1', 'a-1', 'b-3', 'b-1', 'b-2'])

    expect(JSON.parse(localStorage.getItem('test.sidebar.order.order.projects') || 'null'))
      .toEqual(['project-c', 'project-a', 'project-b'])
    expect(JSON.parse(localStorage.getItem('test.sidebar.order.order.sessions') || 'null'))
      .toEqual({
        'project-a': ['a-1'],
        'project-b': ['b-3', 'b-1', 'b-2'],
        'project-c': ['c-1'],
      })

    const restored = mount(SessionSidebar, {
      props: { projectGroups, pinStorageKey: 'test.sidebar.order' },
    })
    expect(restored.findAll('[data-sidebar-section="default"] [data-project-row]')
      .map((row) => row.attributes('data-project-row')))
      .toEqual(['project-c', 'project-a', 'project-b'])
    expect(restored.findAll('[data-sidebar-section="default"] [data-session-row]')
      .map((row) => row.attributes('data-session-row')))
      .toEqual(['c-1', 'a-1', 'b-3', 'b-1', 'b-2'])
  })

  it('keeps the original session order when refreshed metadata changes', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: [{
          id: 'project',
          name: 'Project',
          sessions: [
            { id: 'first', title: 'First', updatedAt: '2026-07-01T08:00:00Z' },
            { id: 'second', title: 'Second', updatedAt: '2026-07-02T08:00:00Z' },
          ],
        }],
      },
    })

    await wrapper.setProps({
      projectGroups: [{
        id: 'project',
        name: 'Project',
        sessions: [
          { id: 'second', title: 'Second', updatedAt: '2026-08-02T08:00:00Z' },
          { id: 'first', title: 'First', updatedAt: '2026-08-01T08:00:00Z' },
        ],
      }],
    })

    expect(wrapper.findAll('[data-sidebar-section="default"] [data-session-row]')
      .map((row) => row.attributes('data-session-row')))
      .toEqual(['first', 'second'])
  })

  it('shows status indicators only for active or failed sessions', () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: [{
          id: 'status-project',
          name: 'Status project',
          sessions: [
            { id: 'running', title: 'Running', status: 'running' },
            { id: 'waiting', title: 'Waiting', status: 'waiting' },
            { id: 'failed', title: 'Failed', status: 'failed' },
            { id: 'completed', title: 'Completed', status: 'completed' },
            { id: 'cancelled', title: 'Cancelled', status: 'cancelled' },
            { id: 'idle', title: 'Idle', status: 'idle' },
          ],
        }],
      },
    })

    for (const id of ['running', 'waiting', 'failed']) {
      expect(wrapper.find(`[data-session-row="${id}"] .session-status`).exists()).toBe(true)
    }
    for (const id of ['completed', 'cancelled', 'idle']) {
      expect(wrapper.find(`[data-session-row="${id}"] .session-status`).exists()).toBe(false)
    }
  })

  it('keeps session actions in the context menu instead of the selection button', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowSessionDelete: true,
      },
      attachTo: document.body,
    })

    const row = wrapper.get('[data-session-row="s1"]')
    const selector = row.get('[data-session-select="s1"]')

    expect(selector.element.tagName).toBe('BUTTON')
    expect(selector.find('[data-session-menu-pin="s1"]').exists()).toBe(false)

    const menu = await openSessionMenu(wrapper, 's1')
    expect(menu.querySelector('[data-session-menu-pin="s1"]')).not.toBeNull()
    await row.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select-session')).toBeUndefined()
  })

  it('exposes the same session menu through a touch-friendly action button', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowSessionDelete: true,
        showSessionActions: true,
      },
      attachTo: document.body,
    })

    const action = wrapper.get('[data-session-menu-trigger="s1"]')
    expect(action.attributes('aria-label')).toBe('One 会话操作')
    await action.trigger('click', { clientX: 120, clientY: 80 })
    await nextTick()
    const menu = document.body.querySelector<HTMLElement>('[data-session-menu="s1"]')
    expect(menu?.textContent).toContain('置顶会话')
    expect(menu?.textContent).toContain('重命名')
    expect(menu?.textContent).toContain('导出')
    expect(menu?.textContent).toContain('删除')
  })

  it('supports pin, rename, export submenu, and delete from the session context menu', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowSessionDelete: true,
        pinStorageKey: 'session-actions',
      },
      attachTo: document.body,
    })

    let menu = await openSessionMenu(wrapper, 's1')
    expect([...menu.querySelectorAll('button')].map((button) => button.textContent?.trim())).toEqual([
      '置顶会话',
      '重命名',
      '导出',
      '删除',
    ])

    dispatchClick(menu.querySelector('[data-session-menu-pin="s1"]')!)
    await nextTick()
    expect(localStorage.getItem('session-actions.sessions')).toBe('["s1"]')

    menu = await openSessionMenu(wrapper, 's1')
    dispatchClick(menu.querySelector('[data-session-menu-rename="s1"]')!)
    await nextTick()
    const input = wrapper.get('[data-session-name-input="s1"]')
    await input.setValue('Renamed')
    await input.trigger('keydown.enter')
    expect(wrapper.emitted('rename-session')).toEqual([['s1', 'Renamed']])

    menu = await openSessionMenu(wrapper, 's1')
    dispatchClick(menu.querySelector('[data-session-menu-export="s1"]')!)
    await nextTick()
    const exportMenu = document.body.querySelector<HTMLElement>('[data-session-export-menu="s1"]')!
    expect(exportMenu).not.toBeNull()
    expect(exportMenu.textContent).toContain('文本记录')
    expect(exportMenu.textContent).toContain('Agent Handoff')
    expect(exportMenu.textContent).toContain('完整归档')
    const markdown = document.body.querySelector<HTMLElement>('[data-session-export-format="markdown"]')!
    dispatchClick(markdown)
    expect(wrapper.emitted('export-session')).toEqual([['s1', 'markdown']])

    menu = await openSessionMenu(wrapper, 's1')
    dispatchClick(menu.querySelector('[data-session-menu-export="s1"]')!)
    await nextTick()
    dispatchClick(document.body.querySelector('[data-session-export-format="handoff"]')!)
    expect(wrapper.emitted('export-session')).toEqual([['s1', 'markdown'], ['s1', 'handoff']])

    menu = await openSessionMenu(wrapper, 's1')
    dispatchClick(menu.querySelector('[data-session-menu-export="s1"]')!)
    await nextTick()
    dispatchClick(document.body.querySelector('[data-session-export-format="zip"]')!)
    expect(wrapper.emitted('export-session')).toEqual([
      ['s1', 'markdown'],
      ['s1', 'handoff'],
      ['s1', 'zip'],
    ])

    menu = await openSessionMenu(wrapper, 's1')
    dispatchClick(menu.querySelector('[data-session-menu-delete="s1"]')!)
    expect(wrapper.emitted('delete-session')).toEqual([['s1']])
  })

  it('closes the session menu on outside pointerdown, Escape, scroll, and session change', async () => {
    const wrapper = mount(SessionSidebar, {
      props: { projectGroups: groups, activeSessionId: 's1' },
      attachTo: document.body,
    })

    await openSessionMenu(wrapper, 's1')
    document.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await nextTick()
    expect(document.body.querySelector('[data-session-menu="s1"]')).toBeNull()

    await openSessionMenu(wrapper, 's1')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()
    expect(document.body.querySelector('[data-session-menu="s1"]')).toBeNull()

    await openSessionMenu(wrapper, 's1')
    document.dispatchEvent(new Event('scroll', { bubbles: true }))
    await nextTick()
    expect(document.body.querySelector('[data-session-menu="s1"]')).toBeNull()

    await openSessionMenu(wrapper, 's1')
    await wrapper.setProps({ activeSessionId: 's2' })
    await nextTick()
    expect(document.body.querySelector('[data-session-menu="s1"]')).toBeNull()
  })
})
