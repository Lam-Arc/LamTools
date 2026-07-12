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

    expect(wrapper.get('[data-sidebar-section="recent"]').text()).toContain('Recent new')
    expect(wrapper.get('[data-sidebar-section="recent"]').text()).toContain('Recent old')
    expect(wrapper.get('[data-sidebar-section="recent"]').findAll('.project-block').map((node) => node.text()))
      .toEqual([expect.stringContaining('Recent new'), expect.stringContaining('Recent old')])
    expect(wrapper.get('[data-sidebar-section="earlier"]').text()).toContain('Earlier')
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
    expect(restored.get('[data-sidebar-section="earlier"]').text()).toContain('Earlier')
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
    expect(sessions[0].get('.conversation-dot').text()).toBe('2')
    expect(localStorage.getItem('test.sidebar.pins.sessions')).toBe('["newer"]')
    expect(wrapper.get('[data-session-pin="newer"]').attributes('aria-pressed')).toBe('true')
  })
})
