import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import RailAction from '../src/components/RailAction.vue'

const shellCss = readFileSync(resolve(import.meta.dirname, '../src/styles/workspace-shell.css'), 'utf8')
const variablesCss = readFileSync(resolve(import.meta.dirname, '../src/styles/variables.css'), 'utf8')
const sidebarCss = readFileSync(resolve(import.meta.dirname, '../src/styles/session-sidebar.css'), 'utf8')

function mountAction() {
  return mount(RailAction, {
    props: {
      actionId: 'settings',
      label: '设置',
      description: '模型与供应商、外观主题、工具权限等应用配置。',
    },
    slots: { default: '<svg data-footer-icon />' },
  })
}

describe('RailAction', () => {
  it('keeps the footer entry icon-only and shows the label in a tip on hover', async () => {
    const wrapper = mountAction()
    const button = wrapper.get('[data-rail-action="settings"]')

    expect(button.text()).toBe('')
    expect(button.attributes('aria-label')).toBe('设置')
    expect(wrapper.find('[data-rail-action-intro]').exists()).toBe(false)

    await wrapper.trigger('mouseenter')
    expect(wrapper.get('.rail-action__tip').text()).toContain('设置')
    // The one-line introduction stays collapsed until the tip's alert glyph is used.
    expect(wrapper.find('[data-rail-action-intro]').exists()).toBe(false)

    await wrapper.trigger('mouseleave')
    expect(wrapper.find('.rail-action__tip').exists()).toBe(false)
    wrapper.unmount()
  })

  it('reveals the introduction while the tip alert glyph is hovered', async () => {
    const wrapper = mountAction()
    await wrapper.trigger('mouseenter')

    const info = wrapper.get('[data-rail-action-info="settings"]')
    await info.trigger('mouseenter')
    expect(wrapper.get('[data-rail-action-intro]').text()).toBe('模型与供应商、外观主题、工具权限等应用配置。')

    // 说明的收起挂在提示自身的离开上：指针跨过提示内部（感叹号与说明之间）时，
    // 正在读的说明不能被收掉。
    await wrapper.get('[data-rail-action-intro]').trigger('mouseenter')
    expect(wrapper.find('[data-rail-action-intro]').exists()).toBe(true)

    await wrapper.get('.rail-action__tip').trigger('mouseleave')
    expect(wrapper.find('[data-rail-action-intro]').exists()).toBe(false)

    // Keyboard users reach the same introduction through focus.
    await info.trigger('focus')
    expect(wrapper.find('[data-rail-action-intro]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('grows the introduction above the label row so the hovered glyph cannot move', async () => {
    const wrapper = mountAction()
    await wrapper.trigger('mouseenter')
    await wrapper.get('[data-rail-action-info="settings"]').trigger('mouseenter')

    // DOM 顺序仍是「标签行 → 说明」，提示用 column-reverse 布局：说明占据标签行
    // 上方的空间，标签行被钉在提示下沿，展开说明时感叹号原地不动。
    const tip = wrapper.get('.rail-action__tip')
    const children = Array.from(tip.element.children).map((child) => child.className)
    expect(children[0]).toContain('rail-action__tip-head')
    expect(children[1]).toContain('rail-action__tip-body')
    expect(shellCss).toMatch(/\.rail-action__tip \{[\s\S]*?flex-direction: column-reverse;/)
    expect(shellCss).toMatch(/\.rail-action__tip-body \{[\s\S]*?margin: 0;/)
    wrapper.unmount()
  })

  it('keeps the tip open while focus moves between the button and the alert glyph', async () => {
    const wrapper = mountAction()
    const button = wrapper.get('[data-rail-action="settings"]')

    await button.trigger('focusin')
    expect(wrapper.find('.rail-action__tip').exists()).toBe(true)

    await wrapper.trigger('focusout', { relatedTarget: wrapper.get('[data-rail-action-info="settings"]').element })
    expect(wrapper.find('.rail-action__tip').exists()).toBe(true)

    await wrapper.trigger('focusout', { relatedTarget: document.body })
    expect(wrapper.find('.rail-action__tip').exists()).toBe(false)
    wrapper.unmount()
  })

  it('emits a single click action from the icon button', async () => {
    const wrapper = mountAction()
    await wrapper.get('[data-rail-action="settings"]').trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
    wrapper.unmount()
  })

  it('anchors the tip as a full-row band so the compact rail cannot clip it', () => {
    // 提示框是触发按钮的后代（悬浮不会中断），但定位相对整行，宽度被左栏限制住。
    expect(shellCss).toMatch(/\.drawer-footer-row \{[\s\S]*?position: relative;/)
    expect(shellCss).toMatch(/\.rail-action__tip \{[\s\S]*?position: absolute;[\s\S]*?left: 0;[\s\S]*?right: 0;/)
    expect(shellCss).toMatch(/\.rail-action__tip--above \{ bottom: 100%; \}/)
    expect(shellCss).toMatch(/\.rail-action__tip--below \{ top: 100%; \}/)
    expect(shellCss).toMatch(/\.rail-action \{ flex: 0 0 auto; \}/)
    // 提示面板沿用卡片配方（不透明底 + 边框 + --shadow-md）。
    expect(shellCss).toMatch(/\.rail-action__tip \{[\s\S]*?border: 1px solid var\(--theme-main-border\);[\s\S]*?background: var\(--theme-main-background\);[\s\S]*?box-shadow: var\(--shadow-md\);/)
    expect(variablesCss).toMatch(/--rail-action-size: 28px/)
    expect(variablesCss).toMatch(/--rail-action-size-full: 32px/)
  })

  it('keeps the left rail width in three tiers and lets the sidebar width drive the icon fold', () => {
    // 小界面 = 紧凑档（--sidebar-width）；窗口宽裕先升中间档；大界面/全屏回到标准宽度。
    expect(variablesCss).toContain('--sidebar-width: 162px')
    expect(variablesCss).toContain('--sidebar-width-mid: 200px')
    expect(variablesCss).toContain('--sidebar-width-full: 232px')
    expect(shellCss).toMatch(/@media \(min-width: 1200px\) \{\s*\.workspace-shell \{\s*--sidebar-width: var\(--sidebar-width-mid\);\s*\}\s*\}/)
    expect(shellCss).toMatch(/@media \(min-width: 1600px\) \{\s*\.workspace-shell \{\s*--sidebar-width: var\(--sidebar-width-full\);\s*--rail-action-size: var\(--rail-action-size-full\);\s*\}\s*\}/)
    // 项目行左侧图标是否让出，跟随侧栏实际宽度（容器查询），不再依赖窗口断点。
    expect(shellCss).toMatch(/\.drawer-left \{[\s\S]*?container: sidebar \/ inline-size;/)
    expect(sidebarCss).toMatch(/@container sidebar \(max-width: 189px\) \{[\s\S]*?\.project-main \{ grid-template-columns: minmax\(0, 1fr\); \}[\s\S]*?\.project-name \.project-visual-icon \{ display: none; \}/)
  })

  it('styles the project name like a session name with a background-leaning tone', () => {
    expect(sidebarCss).toMatch(/\.project-name strong \{[\s\S]*?font-size: var\(--sidebar-font\);[\s\S]*?font-weight: 400;[\s\S]*?color: var\(--sidebar-text-project\);/)
    expect(sidebarCss).not.toMatch(/\.project-name strong \{[\s\S]*?font-weight: 600;/)
    expect(variablesCss).toMatch(/--sidebar-text-project: color-mix\(in srgb, var\(--theme-backdrop-text, var\(--text\)\) 62%, var\(--theme-backdrop-background/)
  })
})
