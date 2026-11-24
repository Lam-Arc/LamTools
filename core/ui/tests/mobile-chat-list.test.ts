import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MobileChatList from '../src/components/MobileChatList.vue'

// user:“项目不应该和环境放在一个选项内，而且可以折叠掉会话的父级标签”+
// (环境是单独一行；项目是可折叠的父级，会话挂在项目下面)。
const groups = [
  {
    id: 'p1',
    name: '默认项目',
    sessions: [
      { id: 's1', title: '会话一', status: 'running', updatedAt: '2026-11-22T10:00:00Z' },
      { id: 's2', title: '会话二', updatedAt: '2026-11-21T10:00:00Z' },
    ],
  },
  {
    id: 'p2',
    name: 'Sunday 开发',
    sessions: [
      { id: 's3', title: '会话三', updatedAt: '2026-11-20T10:00:00Z' },
    ],
  },
]

afterEach(() => {
  localStorage.clear()
  vi.useRealTimers()
})

describe('MobileChatList (L1)', () => {
  it('keeps the environment in its own control, apart from the projects', async () => {
    const wrapper = mount(MobileChatList, {
      props: { groups, environmentName: '本机 Android', activeProjectId: 'p1' },
    })

    const environment = wrapper.get('[data-mobile-chat-environment]')
    expect(environment.text()).toContain('本机 Android')
    // 环境那一行只说设备，不再把项目名字塞进来。
    expect(environment.text()).not.toContain('默认项目')

    await environment.trigger('click')
    expect(wrapper.emitted('pick-environment')).toHaveLength(1)
    wrapper.unmount()
  })

  it('groups sessions under their project and marks the current one', () => {
    const wrapper = mount(MobileChatList, { props: { groups, activeProjectId: 'p2' } })

    const heads = wrapper.findAll('[data-mobile-chat-group-head]')
    expect(heads).toHaveLength(2)
    expect(heads[0].text()).toContain('默认项目')
    expect(heads[1].text()).toContain('Sunday 开发')
    expect(heads[1].text()).toContain('当前')
    expect(heads[0].text()).not.toContain('当前')

    // 会话排在各自项目下，不混成一段。
    expect(wrapper.get('[data-mobile-chat-group="p1"]').text()).toContain('会话一')
    expect(wrapper.get('[data-mobile-chat-group="p2"]').text()).toContain('会话三')
    wrapper.unmount()
  })

  it('collapses the project folder without touching the other projects', async () => {
    const wrapper = mount(MobileChatList, { props: { groups, activeProjectId: 'p1' } })
    const head = wrapper.get('[data-mobile-chat-group-head="p1"]')
    expect(head.attributes('aria-expanded')).toBe('true')

    await head.trigger('click')
    expect(head.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-mobile-chat-session="s1"]').exists()).toBe(false)
    expect(wrapper.find('[data-mobile-chat-session="s2"]').exists()).toBe(false)
    expect(wrapper.find('[data-mobile-chat-session="s3"]').exists()).toBe(true)

    await head.trigger('click')
    expect(head.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-mobile-chat-session="s1"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('opens a session on tap and surfaces the status as the second line', async () => {
    const wrapper = mount(MobileChatList, { props: { groups } })
    const card = wrapper.get('[data-mobile-chat-session="s1"]')
    expect(card.text()).toContain('会话一')
    expect(card.text()).toContain('正在执行')

    await card.trigger('click')
    expect(wrapper.emitted('open')?.[0]).toEqual(['s1'])
    wrapper.unmount()
  })

  it('keeps pinned sessions on top and names the project they came from', () => {
    const wrapper = mount(MobileChatList, {
      props: { groups, pinnedSessionIds: ['s2'] },
    })

    const sections = wrapper.findAll('.mobile-chat-list__section').map(node => node.text())
    expect(sections[0]).toBe('置顶')
    const pinned = wrapper.get('[data-mobile-chat-session="s2"]')
    expect(pinned.text()).toContain('默认项目')
    // 置顶的会话只出现在置顶段，不会在项目分组里再排一次。
    expect(wrapper.findAll('[data-mobile-chat-session="s2"]')).toHaveLength(1)
    wrapper.unmount()
  })

  it('filters inside the projects and expands them while searching', async () => {
    const wrapper = mount(MobileChatList, { props: { groups } })

    await wrapper.get('[data-mobile-chat-group-head="p1"]').trigger('click')
    expect(wrapper.find('[data-mobile-chat-session="s1"]').exists()).toBe(false)

    await wrapper.get('[data-mobile-chat-search-toggle]').trigger('click')
    await wrapper.get('[data-mobile-chat-search]').setValue('会话一')
    expect(wrapper.find('[data-mobile-chat-session="s1"]').exists()).toBe(true)
    expect(wrapper.find('[data-mobile-chat-session="s2"]').exists()).toBe(false)
    expect(wrapper.find('[data-mobile-chat-group="p2"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('emits a session menu after a long press without treating it as a click', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MobileChatList, { props: { groups } })
    const card = wrapper.get('[data-mobile-chat-session="s2"]')

    await card.trigger('pointerdown')
    vi.advanceTimersByTime(500)

    expect(wrapper.emitted('session-menu')?.[0]?.[0]).toBe('s2')
    // 长按后抬起不应再触发打开。
    await card.trigger('pointerup')
    expect(wrapper.emitted('open')).toBeUndefined()
    wrapper.unmount()
  })

  it('opens the project menu on a long press and never folds the folder by accident', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MobileChatList, { props: { groups } })
    const head = wrapper.get('[data-mobile-chat-group-head="p1"]')

    await head.trigger('pointerdown')
    vi.advanceTimersByTime(500)
    expect(wrapper.emitted('project-menu')?.[0]?.[0]).toBe('p1')

    await head.trigger('pointerup')
    expect(wrapper.find('[data-mobile-chat-session="s1"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('offers project creation at the end of the list', async () => {
    const wrapper = mount(MobileChatList, { props: { groups } })
    await wrapper.get('[data-mobile-chat-create-project]').trigger('click')
    expect(wrapper.emitted('create-project')).toHaveLength(1)
    wrapper.unmount()
  })

  it('shows a visible project menu button instead of hiding settings behind a long press', async () => {
    const wrapper = mount(MobileChatList, { props: { groups } })
    const more = wrapper.get('[data-mobile-project-more="p1"]')

    await more.trigger('click')
    expect(wrapper.emitted('project-menu')?.[0]?.[0]).toBe('p1')
    // 点 ⋯ 不应该顺手把分组折叠掉。
    expect(wrapper.find('[data-mobile-chat-session="s1"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows a visible session menu button that does not open the session', async () => {
    const wrapper = mount(MobileChatList, { props: { groups } })

    await wrapper.get('[data-mobile-session-more="s1"]').trigger('click')
    expect(wrapper.emitted('session-menu')?.[0]?.[0]).toBe('s1')
    expect(wrapper.emitted('open')).toBeUndefined()
    wrapper.unmount()
  })

  it('puts the new-session button next to each project', async () => {
    const wrapper = mount(MobileChatList, { props: { groups } })

    const create = wrapper.get('[data-mobile-project-new="p2"]')
    expect(create.attributes('aria-label')).toContain('Sunday 开发')

    await create.trigger('click')
    expect(wrapper.emitted('create-session')?.[0]).toEqual(['p2'])
    // 点 + 不该折叠分组，也不该把会话打开。
    expect(wrapper.find('[data-mobile-chat-session="s3"]').exists()).toBe(true)
    expect(wrapper.emitted('open')).toBeUndefined()
    wrapper.unmount()
  })

  it('drops the click that follows a long press', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MobileChatList, { props: { groups } })

    // 长按会话：菜单弹出后，抬手补发的 click 不能再把会话打开。
    const card = wrapper.get('[data-mobile-chat-session="s1"]')
    await card.trigger('pointerdown')
    vi.advanceTimersByTime(500)
    await card.trigger('pointerup')
    await card.trigger('click')
    expect(wrapper.emitted('session-menu')?.[0]?.[0]).toBe('s1')
    expect(wrapper.emitted('open')).toBeUndefined()

    // 长按项目标题：同样不能顺手折叠。
    const head = wrapper.get('[data-mobile-chat-group-head="p1"]')
    await head.trigger('pointerdown')
    vi.advanceTimersByTime(500)
    await head.trigger('pointerup')
    await head.trigger('click')
    expect(wrapper.find('[data-mobile-chat-session="s1"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
