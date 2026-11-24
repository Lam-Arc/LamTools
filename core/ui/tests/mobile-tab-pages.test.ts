import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MobileTabsDrawer from '../src/components/MobileTabsDrawer.vue'
import MobileChatHeader from '../src/components/MobileChatHeader.vue'

const read = (relativePath: string): string => readFileSync(resolve(import.meta.dirname, '..', relativePath), 'utf8')
const appSource = read('src/app/LamToolsApp.vue')
const headerSource = read('src/components/MobileChatHeader.vue')
const shellCss = read('src/styles/workspace-shell.css')

/**
 * user:“桌面的分屏标签页对于手机来说，等于换页”+
 * “注意出入口，进来页之后要能切、能返回”+(手机没有并排：标签就是页；抽屉既是入口、
 * 也是页与页之间的切换器，还是回到会话与关掉某一页的出口)。
 */
describe('mobile tab pages', () => {
  const tabs = [
    { id: 't1', title: '搜索结果', kind: 'browser' },
    { id: 't2', title: 'report.pdf', kind: 'file' },
  ]

  it('lists the conversation first and emits a page switch', async () => {
    const wrapper = mount(MobileTabsDrawer, {
      props: { open: true, activeId: '', sessionTitle: '手机端验收', tabs },
      global: { stubs: { Teleport: true } },
    })
    const rows = wrapper.findAll('[data-mobile-tabs-row]')
    expect(rows).toHaveLength(2)
    expect(wrapper.find('[data-mobile-tabs-conversation]').text()).toContain('手机端验收')

    await wrapper.find('[data-mobile-tabs-item="t2"]').trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual(['t2'])

    await wrapper.find('[data-mobile-tabs-conversation]').trigger('click')
    expect(wrapper.emitted('select')?.[1]).toEqual([''])
  })

  it('closes one page without touching the others', async () => {
    const wrapper = mount(MobileTabsDrawer, {
      props: { open: true, activeId: 't1', sessionTitle: '会话', tabs },
      global: { stubs: { Teleport: true } },
    })
    await wrapper.find('[data-mobile-tabs-close="t1"]').trigger('click')
    expect(wrapper.emitted('close-tab')?.[0]).toEqual(['t1'])
    expect(wrapper.findAll('[data-mobile-tabs-row]')).toHaveLength(2)
  })

  it('marks the page you are on', () => {
    const wrapper = mount(MobileTabsDrawer, {
      props: { open: true, activeId: 't1', sessionTitle: '会话', tabs },
      global: { stubs: { Teleport: true } },
    })
    expect(wrapper.find('[data-mobile-tabs-row="t1"]').classes()).toContain('is-active')
    expect(wrapper.find('[data-mobile-tabs-conversation]').attributes('aria-current')).toBeUndefined()
  })

  it('offers the drawer from the session header, with the page title and a count', async () => {
    const wrapper = mount(MobileChatHeader, {
      props: { title: '会话', pageTitle: '搜索结果', tabsCount: 2, deviceLabel: '本机 Android', deviceState: 'local' },
    })
    expect(wrapper.find('[data-mobile-chat-header-title]').text()).toBe('搜索结果')
    expect(wrapper.find('[data-mobile-chat-tabs-count]').text()).toBe('2')
    await wrapper.find('[data-mobile-chat-tabs]').trigger('click')
    expect(wrapper.emitted('tabs')).toHaveLength(1)
    // 返回键交给宿主：页上先回会话，会话里再回列表。
    await wrapper.find('[data-mobile-chat-back]').trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)
  })

  it('hides the drawer entry when there is no page to switch to', () => {
    const wrapper = mount(MobileChatHeader, {
      props: { title: '会话', tabsCount: 0, deviceLabel: '本机 Android' },
    })
    expect(wrapper.find('[data-mobile-chat-tabs]').exists()).toBe(false)
  })

  it('keeps the split layer closed on a phone until a page is chosen', () => {
    // 手机不借用桌面分屏槽：页走自己的整页容器；Agent 自己开的页只进抽屉。
    expect(appSource).toContain(`v-if="appRuntime.platform !== 'mobile'"`)
    expect(appSource).toContain('data-mobile-page')
    expect(appSource).toContain('<CoreSplitContent')
    expect(appSource).toContain('mobileQuietTabIds.add(adopted.id)')
    expect(headerSource).toContain('data-mobile-chat-tabs')
    expect(shellCss).toMatch(/\.mobile-page \{[\s\S]*?position: fixed;/)
  })

  it('returns from a page to the conversation before leaving the chat', () => {
    expect(appSource).toMatch(/function onMobileChatBack\(\): void \{\s*if \(mobilePageId\.value\) \{\s*leaveMobilePage\(\)\s*return\s*\}\s*backToMobileChatList\(\)/)
    expect(appSource).toMatch(/function openMobilePage\(id: string\): void \{[\s\S]*?workspace\.activate\(entry\.pane, entry\.tab\.id\)[\s\S]*?mobilePageId\.value = id/)
  })

  it('hides the previous native web view before switching to a file', () => {
    const start = appSource.indexOf('watch(mobilePageTab,')
    const end = appSource.indexOf('const mobilePageTitle', start)
    const watcher = appSource.slice(start, end)
    expect(watcher).toMatch(/previous\??\.tab\.kind === 'browser'/)
    expect(watcher).toMatch(/browser_hide[\s\S]*?previous\.tab\.id/)
    expect(watcher.indexOf('browser_hide')).toBeLessThan(watcher.indexOf('settleMobilePage'))
  })
})
