import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

// user:“改用官方 window API，不再依赖全局注入”+(测试用假 getCurrentWindow，断言三个按钮各自调用官方方法)。
const winMock = vi.hoisted(() => ({
  minimize: vi.fn(async () => undefined),
  toggleMaximize: vi.fn(async () => undefined),
  close: vi.fn(async () => undefined),
  throwing: false,
}))

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => {
    if (winMock.throwing) throw new Error('not in tauri')
    return winMock
  },
}))

import TitleBar from '../src/components/TitleBar.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  winMock.minimize.mockClear()
  winMock.toggleMaximize.mockClear()
  winMock.close.mockClear()
  winMock.throwing = false
  vi.restoreAllMocks()
})

async function mountBar() {
  const wrapper = mount(TitleBar, { props: { showInPreview: true } })
  wrappers.push(wrapper)
  await wrapper.vm.$nextTick()
  return wrapper
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0))

// user:“窗口三键还没通…直接把实现换成不依赖任何全局注入的官方路径”+
// (三个按钮分别调 getCurrentWindow().minimize / toggleMaximize / close)。
describe('窗口三键：官方 window API', () => {
  it('最小化/最大化/关闭各自调用官方方法，并用 console.error 打一条 [window-ctl]', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    const wrapper = await mountBar()

    await wrapper.get('[data-window-control="minimize"]').trigger('click')
    expect(winMock.minimize).toHaveBeenCalledTimes(1)

    await wrapper.get('[data-window-control="maximize"]').trigger('click')
    expect(winMock.toggleMaximize).toHaveBeenCalledTimes(1)

    await wrapper.get('[data-window-control="close"]').trigger('click')
    expect(winMock.close).toHaveBeenCalledTimes(1)

    await settle()
    const logged = error.mock.calls.filter(call => call[0] === '[window-ctl]')
    expect(logged.map(call => call[1])).toEqual([
      { command: 'minimize', ok: true },
      { command: 'toggleMaximize', ok: true },
      { command: 'close', ok: true },
    ])
  })

  it('官方方法失败时也打印 ok:false 与错误文本（不再静默）', async () => {
    winMock.minimize.mockRejectedValueOnce(new Error('permission denied'))
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    const wrapper = await mountBar()
    await wrapper.get('[data-window-control="minimize"]').trigger('click')
    await settle()
    const entry = error.mock.calls.find(call => call[0] === '[window-ctl]')
    expect(entry![1]).toMatchObject({ command: 'minimize', ok: false })
    expect(String((entry![1] as { error: string }).error)).toContain('permission denied')
  })

  it('非 Tauri 环境（getCurrentWindow 抛错）时 dev 里留一条 error，且不崩溃', async () => {
    winMock.throwing = true
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    const wrapper = await mountBar()
    await wrapper.get('[data-window-control="maximize"]').trigger('click')
    const entry = error.mock.calls.find(call => call[0] === '[window-ctl]')
    expect(entry![1]).toMatchObject({ command: 'toggleMaximize', ok: false })
    expect(String((entry![1] as { error: string }).error)).toContain('not in tauri')
    // 三个按钮仍在（没有因为抛错把整条链断掉）
    expect(wrapper.find('[data-window-control="close"]').exists()).toBe(true)
  })

  it('三个按钮是原生 button、带 aria-label，且挂载期间不再监听遗留原生事件', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const wrapper = await mountBar()
    for (const name of ['minimize', 'maximize', 'close']) {
      const button = wrapper.get(`[data-window-control="${name}"]`)
      expect(button.element.tagName).toBe('BUTTON')
      expect(button.attributes('aria-label')).toBeTruthy()
    }
    const names = addSpy.mock.calls.map(call => call[0])
    expect(names).not.toContain('lamtools:maximize-hover')
    expect(names).not.toContain('lamtools:maximize-press')
  })
})

// user:“别再靠日志推断了…改成官方 API”+(源码锁：命令名与全局注入都不许再出现；
//  日志必须走 console.error —— 前端落盘只收 warn/error，之前用 info 所以一条都看不到)。
describe('实现只在官方路径上（源码锁）', () => {
  const source = readFileSync(resolve(__dirname, '../src/components/TitleBar.vue'), 'utf8')

  it('用 getCurrentWindow，不再手拼命令名或读全局注入', () => {
    expect(source).toContain("from '@tauri-apps/api/window'")
    expect(source).toContain('getCurrentWindow()')
    expect(source).not.toContain('minimize_window')
    expect(source).not.toContain('toggle_maximize_window')
    expect(source).not.toContain('close_window')
    expect(source).not.toContain('__TAURI_INTERNALS__.invoke')
  })

  it('失败可见走 console.error，且仍带 [window-ctl] 前缀', () => {
    expect(source).toContain("console.error('[window-ctl]'")
    expect(source).not.toContain("console.info('[window-ctl]'")
  })
})
