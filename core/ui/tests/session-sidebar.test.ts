import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SessionSidebar from '../src/components/SessionSidebar.vue'

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

describe('SessionSidebar sections', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-13T08:00:00Z'))
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

  it('pins projects durably and restores them in the pinned section', async () => {
    const wrapper = mount(SessionSidebar, {
      props: { projectGroups: groups, pinStorageKey: 'test.sidebar.pins' },
    })

    await wrapper.get('[data-project-menu-trigger="earlier"]').trigger('click')
    await wrapper.get('[data-project-pin="earlier"]').trigger('click')

    expect(wrapper.get('[data-sidebar-section="pinned"]').text()).toContain('Earlier')
    expect(localStorage.getItem('test.sidebar.pins')).toBe('["earlier"]')

    const restored = mount(SessionSidebar, {
      props: { projectGroups: groups, pinStorageKey: 'test.sidebar.pins' },
    })
    expect(restored.get('[data-sidebar-section="pinned"]').text()).toContain('Earlier')

    await restored.get('[data-project-menu-trigger="earlier"]').trigger('click')
    await restored.get('[data-project-pin="earlier"]').trigger('click')
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

    const menu = wrapper.get('[data-project-menu="recent-new"]')
    expect(menu.attributes('role')).toBe('menu')
    expect(menu.text()).toContain('新建会话')
    expect(menu.text()).toContain('置顶项目')
    expect(menu.text()).toContain('项目设置')
    expect(menu.text()).toContain('删除项目')
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
      ['[data-project-menu="recent-new"] button:nth-last-of-type(2)', 'project-context-menu'],
      ['[data-project-menu="recent-new"] button:last-of-type', 'delete-project'],
    ] as const) {
      await wrapper.get('[data-project-menu-trigger="recent-new"]').trigger('click')
      const action = wrapper.get(selector)
      await action.trigger('pointerdown')
      expect(wrapper.find('[data-project-menu="recent-new"]').exists()).toBe(true)
      await action.trigger('click')
      if (event) expect(wrapper.emitted(event)?.at(-1)).toEqual(['recent-new'])
    }
  })

  it('selects a session when its title text is clicked', async () => {
    const wrapper = mount(SessionSidebar, { props: { projectGroups: groups } })

    await wrapper.get('.conversation strong').trigger('click')

    expect(wrapper.emitted('select-session')).toEqual([['s1']])
    expect(wrapper.find('.session-name-input').exists()).toBe(false)
  })

  it('pins a session from its hover actions and keeps its original ordinal', async () => {
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

    await wrapper.get('[data-session-pin="newer"]').trigger('click')

    const sessions = wrapper.findAll('.conversation')
    expect(sessions[0].text()).toContain('Newer')
    expect(sessions[0].find('.status.conversation-status.running').exists()).toBe(true)
    expect(localStorage.getItem('test.sidebar.pins.sessions')).toBe('["newer"]')
    expect(wrapper.get('[data-session-pin="newer"]').attributes('aria-pressed')).toBe('true')
  })

  it('keeps session actions separate from the session selection button', async () => {
    const wrapper = mount(SessionSidebar, {
      props: {
        projectGroups: groups,
        allowSessionDelete: true,
      },
    })

    const row = wrapper.get('[data-session-row="s1"]')
    const selector = row.get('[data-session-select="s1"]')
    const pin = row.get('[data-session-pin="s1"]')

    expect(selector.element.tagName).toBe('BUTTON')
    expect(selector.find('[data-session-pin="s1"]').exists()).toBe(false)

    await pin.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select-session')).toBeUndefined()
  })
})
