import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import UiSelect from '../src/components/UiSelect.vue'

// 菜单传送到 body：不自动卸载就会留下上一轮的菜单，后续用例查到的会是旧节点。
enableAutoUnmount(afterEach)

const options = [
  { value: 'a', label: '选项甲' },
  { value: 'b', label: '选项乙' },
]

function mountSelect(props: Record<string, unknown> = {}, attachTo?: HTMLElement) {
  return mount(UiSelect, {
    props: { modelValue: 'a', options, ariaLabel: '测试选择', ...props },
    attachTo,
  })
}

function rectOf(right: number, width = 120, bottom = 40): DOMRect {
  return {
    x: right - width,
    y: bottom - 40,
    top: bottom - 40,
    left: right - width,
    bottom,
    right,
    width,
    height: 40,
    toJSON: () => ({}),
  } as DOMRect
}

/** jsdom 视口 1024 × 768；只给触发器几何，菜单自身在 jsdom 里高度恒为 0。 */
function mockTriggerRect(right: number, width = 120, bottom = 40) {
  const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
  spy.mockReturnValue(rectOf(right, width, bottom))
  return spy
}

function mountTriggered(right: number, width = 120, bottom = 40, props: Record<string, unknown> = {}) {
  mockTriggerRect(right, width, bottom)
  return mountSelect(props)
}

async function openMenu(wrapper: ReturnType<typeof mountSelect>): Promise<void> {
  await wrapper.get('.ui-select-trigger').trigger('click')
  await flushPromises()
}

function teleportedMenu(): HTMLElement | null {
  return document.body.querySelector('.ui-select-menu')
}

describe('UiSelect menu alignment', () => {
  afterEach(() => vi.restoreAllMocks())

  it('flips the menu to the right when it would spill past the viewport', async () => {
    // jsdom 视口 1024 宽：触发器右缘 900 + 菜单最窄 280 > 视口内缩 8px。
    const wrapper = mountTriggered(900)
    await openMenu(wrapper)
    expect(wrapper.get('.ui-select').classes()).toContain('ui-select--right')
  })

  it('stays left-aligned when there is room to the right', async () => {
    const wrapper = mountTriggered(100)
    await openMenu(wrapper)
    expect(wrapper.get('.ui-select').classes()).not.toContain('ui-select--right')
  })

  it('honours a forced right alignment', async () => {
    const wrapper = mountTriggered(100, 120, 40, { menuAlign: 'right' })
    await openMenu(wrapper)
    expect(wrapper.get('.ui-select').classes()).toContain('ui-select--right')
  })

  it('honours a forced left alignment even near the edge', async () => {
    const wrapper = mountTriggered(1900, 120, 40, { menuAlign: 'left' })
    await openMenu(wrapper)
    expect(wrapper.get('.ui-select').classes()).not.toContain('ui-select--right')
  })
})

describe('UiSelect menus escape the card that holds the trigger', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders the menu outside a clipping ancestor', async () => {
    const card = document.createElement('div')
    card.style.overflow = 'hidden'
    document.body.appendChild(card)

    const wrapper = mountSelect({}, card)
    mockTriggerRect(400)
    await openMenu(wrapper)

    const menu = teleportedMenu()
    expect(menu).not.toBeNull()
    expect(card.contains(menu)).toBe(false)
    expect(menu!.parentElement).toBe(document.body)

    wrapper.unmount()
    card.remove()
  })

  it('anchors the menu to the trigger in viewport coordinates', async () => {
    const wrapper = mountTriggered(300, 120, 200)
    await openMenu(wrapper)

    const menu = teleportedMenu()!
    expect(menu.style.left).toBe('180px')
    // 下方空间充裕：菜单挂在触发器下缘 + 6px 间隙处。
    expect(menu.style.top).toBe('206px')
    expect(menu.style.bottom).toBe('auto')
    expect(menu.style.visibility).toBe('visible')

    wrapper.unmount()
  })

  it('right-aligns the menu to the trigger edge instead of the page', async () => {
    const wrapper = mountTriggered(1020, 120, 200, { menuAlign: 'right' })
    await openMenu(wrapper)

    const menu = teleportedMenu()!
    // 触发器右缘 1020 - 菜单宽 280 = 740，再按视口右内缩收到 736。
    expect(menu.style.left).toBe('736px')
    expect(Number.parseFloat(menu.style.left)).toBeLessThanOrEqual(1024 - 8 - 280)

    wrapper.unmount()
  })

  it('opens upward when the trigger sits too low for the menu', async () => {
    const wrapper = mountTriggered(300, 120, 700)
    await openMenu(wrapper)

    const menu = teleportedMenu()!
    expect(menu.className).toContain('ui-select-menu--up')
    expect(menu.style.top).toBe('auto')
    // 视口高 768 - 触发器上缘 660 + 6px 间隙。
    expect(menu.style.bottom).toBe('114px')

    wrapper.unmount()
  })

  it('flips a preferred upward menu back down when there is no room above', async () => {
    mockTriggerRect(300, 120, 80)
    const wrapper = mountSelect({ direction: 'up' })
    await openMenu(wrapper)

    const menu = teleportedMenu()!
    expect(menu.className).not.toContain('ui-select-menu--up')
    expect(menu.style.top).toBe('86px')

    wrapper.unmount()
  })

  it('caps the menu height at the room actually available', async () => {
    // 触发器下缘 740：下方只剩 14px，向上展开时按上方空间封顶（不超过 320）。
    const wrapper = mountTriggered(300, 120, 740)
    await openMenu(wrapper)

    const menu = teleportedMenu()!
    const maxHeight = Number.parseFloat(menu.style.maxHeight)
    expect(menu.className).toContain('ui-select-menu--up')
    expect(maxHeight).toBeLessThanOrEqual(320)
    expect(maxHeight).toBeGreaterThanOrEqual(96)

    wrapper.unmount()
  })

  it('follows the trigger when the viewport changes', async () => {
    const rect = mockTriggerRect(300, 120, 200)
    const wrapper = mountSelect()
    await openMenu(wrapper)
    expect(teleportedMenu()!.style.top).toBe('206px')

    rect.mockReturnValue(rectOf(300, 120, 320))
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(teleportedMenu()!.style.top).toBe('326px')

    wrapper.unmount()
  })

  it('carries the scoped control tokens onto the teleported menu', async () => {
    const wrapper = mountSelect()
    mockTriggerRect(300)
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      getPropertyValue: (name: string) => (name === '--settings-control-solid' ? 'rgb(1, 2, 3)' : ''),
    } as unknown as CSSStyleDeclaration)
    await openMenu(wrapper)

    expect(teleportedMenu()!.style.getPropertyValue('--settings-control-solid')).toBe('rgb(1, 2, 3)')

    wrapper.unmount()
  })

  it('selects from the teleported menu instead of treating the click as an outside dismiss', async () => {
    const wrapper = mountTriggered(300, 120, 200)
    await openMenu(wrapper)

    const option = Array.from(document.body.querySelectorAll<HTMLElement>('.ui-select-option'))
      .find((item) => item.textContent?.trim() === '选项乙')!
    option.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    option.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    expect(wrapper.emitted('update:modelValue')).toEqual([['b']])
    expect(teleportedMenu()).toBeNull()

    wrapper.unmount()
  })

  it('closes the teleported menu on an outside pointer down', async () => {
    const wrapper = mountTriggered(300, 120, 200)
    await openMenu(wrapper)
    expect(teleportedMenu()).not.toBeNull()

    document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(teleportedMenu()).toBeNull()

    wrapper.unmount()
  })
})
