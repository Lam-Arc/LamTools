/**
 * Pin 环快捷键录制：纯转换函数与录制判定规则的单元测试。
 *
 * user:“修改代码前充分理解需求，先写能证明需求达成的验收测试”+(这里覆盖的正是
 * 需求里点名的六条：Ctrl+Alt+Space、Shift+F8、单独修饰键被拒、Esc 取消、
 * 非法键被拒、大小写归一；全部是纯逻辑，不启动桌面端。)
 */
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import PetHotkeyField from '@/pet/ui/PetHotkeyField.vue'
import {
  captureHotkey,
  formatHotkeyLabel,
  hotkeyTokenLabel,
  isDesktopRegistrableKey,
  isReservedAccelerator,
  modifiersFrom,
  RESERVED_HOTKEY_REASON,
  translateKeyName,
  type HotkeyKeyInput,
} from '@/pet/ui/hotkeyAccelerator.ts'

function press(key: string, modifiers: Omit<HotkeyKeyInput, 'key'> = {}): ReturnType<typeof captureHotkey> {
  return captureHotkey({ key, ...modifiers })
}

describe('translateKeyName：KeyboardEvent.key → accelerator 键名', () => {
  it('把空格、功能键、字母、数字翻成 accelerator 键名', () => {
    expect(translateKeyName(' ')).toBe('Space')
    expect(translateKeyName('Space')).toBe('Space')
    expect(translateKeyName('F8')).toBe('F8')
    expect(translateKeyName('f8')).toBe('F8')
    expect(translateKeyName('a')).toBe('A')
    expect(translateKeyName('A')).toBe('A')
    expect(translateKeyName('0')).toBe('0')
    expect(translateKeyName('Tab')).toBe('Tab')
    expect(translateKeyName('Enter')).toBe('Enter')
    expect(translateKeyName('Backspace')).toBe('Backspace')
    expect(translateKeyName('ArrowUp')).toBe('ArrowUp')
  })

  it('不产出浏览器里不存在的键名：认不出的键返回 null', () => {
    expect(translateKeyName('Dead')).toBeNull()
    expect(translateKeyName('Unidentified')).toBeNull()
    expect(translateKeyName('MediaPlayPause')).toBeNull()
    expect(translateKeyName('F25')).toBeNull()
    expect(translateKeyName('')).toBeNull()
  })
})

describe('captureHotkey：录制判定', () => {
  it('Ctrl+Alt+Space 直接完成绑定', () => {
    const result = press(' ', { ctrlKey: true, altKey: true })
    expect(result).toEqual({
      status: 'captured',
      accelerator: 'Ctrl+Alt+Space',
      label: 'Ctrl + Alt + 空格',
    })
  })

  it('Shift+F8 直接完成绑定', () => {
    const result = press('F8', { shiftKey: true })
    expect(result).toEqual({ status: 'captured', accelerator: 'Shift+F8', label: 'Shift + F8' })
  })

  it('修饰键顺序固定，不受按下先后影响', () => {
    expect(press('k', { shiftKey: true, altKey: true, ctrlKey: true })).toMatchObject({
      accelerator: 'Ctrl+Alt+Shift+K',
    })
    expect(press('k', { metaKey: true, ctrlKey: true })).toMatchObject({ accelerator: 'Ctrl+Super+K' })
  })

  it('只按修饰键不算绑定，留在录制态', () => {
    for (const key of ['Control', 'Shift', 'Alt', 'Meta', 'AltGraph', 'CapsLock']) {
      const result = press(key, { ctrlKey: true, altKey: true })
      expect(result.status).toBe('pending')
    }
    expect(press('Control', { ctrlKey: true })).toEqual({ status: 'pending', hint: 'Ctrl + …' })
    expect(press('Control')).toEqual({ status: 'pending', hint: '请按下组合键' })
  })

  it('Esc 取消录制，带修饰键也照样取消', () => {
    expect(press('Escape')).toEqual({ status: 'cancelled' })
    expect(press('Esc')).toEqual({ status: 'cancelled' })
    expect(press('Escape', { ctrlKey: true, altKey: true })).toEqual({ status: 'cancelled' })
  })

  it('缺少修饰键被拒：单个键不能注册成全局热键', () => {
    const result = press('a')
    expect(result.status).toBe('rejected')
    expect(result).toMatchObject({ reason: expect.stringContaining('Ctrl / Alt / Shift / Win') })
  })

  it('非法键被拒', () => {
    for (const key of ['Dead', 'Unidentified', 'MediaPlayPause']) {
      const result = press(key, { ctrlKey: true })
      expect(result.status).toBe('rejected')
      expect(result).toMatchObject({ reason: expect.stringContaining('不支持的按键') })
    }
  })

  it('桌面端解析不了的主键被拒，而不是绑定一个按不出反应的热键', () => {
    for (const key of ['ArrowUp', 'Backspace', 'Delete', 'PageDown']) {
      const result = press(key, { ctrlKey: true })
      expect(result.status).toBe('rejected')
      expect(result).toMatchObject({ reason: expect.stringContaining('桌面端暂不支持') })
    }
  })

  it('Sunday 已占用的组合被拒：Ctrl+K 与 Ctrl+Alt+Shift+R', () => {
    for (const input of [
      { key: 'k', ctrlKey: true },
      { key: 'K', ctrlKey: true },
      { key: 'r', ctrlKey: true, altKey: true, shiftKey: true },
      { key: 'r', altKey: true, shiftKey: true, ctrlKey: true },
    ]) {
      const result = captureHotkey(input)
      expect(result.status).toBe('rejected')
      expect(result).toEqual({ status: 'rejected', reason: RESERVED_HOTKEY_REASON })
    }
    expect(RESERVED_HOTKEY_REASON).toBe('该组合已被 Sunday 占用，请换一个')
  })

  it('保留组合旁边的组合仍能绑定', () => {
    expect(press('k', { ctrlKey: true, shiftKey: true })).toMatchObject({ accelerator: 'Ctrl+Shift+K' })
    expect(press('r', { ctrlKey: true, altKey: true })).toMatchObject({ accelerator: 'Ctrl+Alt+R' })
  })

  it('长按重复事件不重复绑定', () => {
    expect(press('k', { ctrlKey: true, repeat: true }).status).toBe('pending')
  })

  it('大小写归一：Shift+a 与 a 记成同一个 A', () => {
    expect(press('a', { ctrlKey: true, shiftKey: true })).toMatchObject({ accelerator: 'Ctrl+Shift+A' })
    expect(press('A', { ctrlKey: true, shiftKey: true })).toMatchObject({ accelerator: 'Ctrl+Shift+A' })
    expect(press('space', { ctrlKey: true })).toMatchObject({ accelerator: 'Ctrl+Space' })
  })
})

describe('可读标签', () => {
  it('accelerator 不直接显示给用户', () => {
    expect(formatHotkeyLabel('Ctrl+Alt+Space')).toBe('Ctrl + Alt + 空格')
    expect(formatHotkeyLabel('Shift+F8')).toBe('Shift + F8')
    expect(formatHotkeyLabel('Super+Tab')).toBe('Win + Tab')
    expect(formatHotkeyLabel('Meta+ArrowUp')).toBe('Win + ↑')
  })

  it('空热键显示未设置', () => {
    expect(formatHotkeyLabel('')).toBe('未设置')
    expect(formatHotkeyLabel('   ')).toBe('未设置')
    expect(formatHotkeyLabel(null)).toBe('未设置')
    expect(formatHotkeyLabel(undefined)).toBe('未设置')
  })

  it('未知 token 原样显示，不丢信息', () => {
    expect(hotkeyTokenLabel('Ctrl')).toBe('Ctrl')
    expect(hotkeyTokenLabel('Numpad0')).toBe('Numpad0')
  })
})

describe('修饰键提取', () => {
  it('只取真实按下的修饰键并保持固定顺序', () => {
    expect(modifiersFrom({ key: 'k', ctrlKey: true, altKey: true, shiftKey: true, metaKey: true })).toEqual([
      'Ctrl',
      'Alt',
      'Shift',
      'Super',
    ])
    expect(modifiersFrom({ key: 'k' })).toEqual([])
  })
})

describe('桌面端可注册主键白名单', () => {
  it('与 platform.rs 的 vk_for_key 对齐', () => {
    for (const key of ['Space', 'Tab', 'Enter', 'A', 'Z', '0', '9', 'F1', 'F12', 'F24']) {
      expect(isDesktopRegistrableKey(key)).toBe(true)
    }
    for (const key of ['Backspace', 'ArrowUp', 'Delete', 'F25', 'KeyA', 'Spacebar']) {
      expect(isDesktopRegistrableKey(key)).toBe(false)
    }
  })
})

/**
 * 组件级接线验证：录制按钮、aria 状态、Esc 取消、清除与恢复默认是不是真的接通了。
 * 这些在 jsdom 里能跑，不启动桌面端。
 */
describe('PetHotkeyField：录制接线', () => {
  function pressKeys(init: KeyboardEventInit): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }))
  }

  it('界面显示可读标签，点录制后按 Ctrl+Alt+Space 完成绑定', async () => {
    const wrapper = mount(PetHotkeyField, { props: { accelerator: 'Ctrl+Alt+Space' } })
    expect(wrapper.get('.hotkey__value').text()).toBe('Ctrl + Alt + 空格')
    expect(wrapper.get('.hotkey__record').attributes('aria-pressed')).toBe('false')

    await wrapper.get('.hotkey__record').trigger('click')
    expect(wrapper.get('.hotkey__record').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[role="status"]').text()).toContain('请按下组合键')

    pressKeys({ key: ' ', ctrlKey: true, altKey: true })
    await nextTick()

    expect(wrapper.emitted('commit')).toEqual([['Ctrl+Alt+Space']])
    expect(wrapper.get('.hotkey__record').attributes('aria-pressed')).toBe('false')
    wrapper.unmount()
  })

  it('Esc 退出录制，不产出绑定', async () => {
    const wrapper = mount(PetHotkeyField, { props: { accelerator: 'Ctrl+Alt+Space' } })
    await wrapper.get('.hotkey__record').trigger('click')

    pressKeys({ key: 'Escape' })
    await nextTick()

    expect(wrapper.emitted('commit')).toBeUndefined()
    expect(wrapper.get('.hotkey__record').attributes('aria-pressed')).toBe('false')
    expect(wrapper.get('[role="status"]').text()).toBe('已取消录制')
    wrapper.unmount()
  })

  it('只按修饰键留在录制态并提示已按下的修饰键', async () => {
    const wrapper = mount(PetHotkeyField, { props: { accelerator: '' } })
    await wrapper.get('.hotkey__record').trigger('click')

    pressKeys({ key: 'Control', ctrlKey: true })
    await nextTick()

    expect(wrapper.emitted('commit')).toBeUndefined()
    expect(wrapper.get('.hotkey__record').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[role="status"]').text()).toBe('Ctrl + …')
    wrapper.unmount()
  })

  it('录到 Ctrl+K 时拒绝并留在录制态', async () => {
    const wrapper = mount(PetHotkeyField, { props: { accelerator: 'Ctrl+Alt+Space' } })
    await wrapper.get('.hotkey__record').trigger('click')

    pressKeys({ key: 'k', ctrlKey: true })
    await nextTick()

    expect(wrapper.emitted('commit')).toBeUndefined()
    expect(wrapper.get('[role="status"]').text()).toBe('该组合已被 Sunday 占用，请换一个')
    expect(wrapper.get('.hotkey__record').attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })

  it('清除写回空值，恢复默认写回默认值', async () => {
    const wrapper = mount(PetHotkeyField, { props: { accelerator: 'Shift+F8' } })
    const buttons = wrapper.findAll('button')
    const clearButton = buttons.find(button => button.text() === '清除')
    const resetButton = buttons.find(button => button.text() === '恢复默认')

    await clearButton?.trigger('click')
    await resetButton?.trigger('click')

    expect(wrapper.emitted('commit')).toEqual([[''], ['Ctrl+Alt+Space']])
    wrapper.unmount()
  })
})
