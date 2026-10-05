import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { gsap } from 'gsap'

import CoreSendStopButton from '../src/components/CoreSendStopButton.vue'

/**
 * 发送/停止按钮的过渡中断与收尾。
 *
 * 单独成文件：这些用例要把真实动效跑起来，与同组件其它"减少动态效果"用例
 * 放在一起会被它们的全局动效状态带偏。gsap.ticker.tick() 按真实时钟推进
 * （它的入参会被忽略），所以"过渡中段"用真实动画测得的形变值直接摆好，
 * 只让组件走中断这条分支；收尾则靠真实等待跨过过渡时长。
 */

function mediaQuery(matches: boolean): MediaQueryList {
  return {
    matches,
    media: '(prefers-reduced-motion: reduce)',
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  } as unknown as MediaQueryList
}

function mountButton() {
  return mount(CoreSendStopButton, {
    attachTo: document.body,
    props: { actionMode: 'send' },
  })
}

describe('CoreSendStopButton transition abort', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('leaves no residual squash when an in-flight send/stop transition is aborted', async () => {
    // 运行态一闪而过（例如一条命令几十毫秒内失败）时，发送/停止会在中途翻回去。
    // 半途被杀掉的 timeline 会把按钮留在压扁的形变上——发送键就一直是个椭圆。
    vi.stubGlobal('matchMedia', () => mediaQuery(false))
    const wrapper = mountButton()
    const button = wrapper.get('button').element as HTMLButtonElement
    try {
      // 环境自检：动效必须是开着的（否则这条用例只是空跑）。
      expect(window.matchMedia('(prefers-reduced-motion: reduce)').matches).toBe(false)

      await wrapper.setProps({ actionMode: 'stop' })
      gsap.ticker.tick()
      // 过渡中段：这些是真实动画在这一段施加的值（压扁 + 字形飞走），
      // 也正是被杀掉后最容易留在屏幕上的状态。
      gsap.set(button, {
        scaleX: 1.0535,
        scaleY: 0.9251,
        '--glyph-opacity': 0,
        '--trail-opacity': 0.58,
      })
      expect(Number(gsap.getProperty(button, 'scaleY'))).toBeLessThan(1)

      await wrapper.setProps({ actionMode: 'send' })
      expect(button.dataset.state).toBe('send')
      expect(Number(gsap.getProperty(button, 'scaleX'))).toBe(1)
      expect(Number(gsap.getProperty(button, 'scaleY'))).toBe(1)
      expect(button.style.transform).toBe('')
      expect(Number(gsap.getProperty(button, '--glyph-opacity'))).toBe(1)
      expect(Number(gsap.getProperty(button, '--trail-opacity'))).toBe(0)

      // 之后也不再被残留的 timeline 改动。
      await new Promise((resolve) => setTimeout(resolve, 400))
      gsap.ticker.tick()
      expect(Number(gsap.getProperty(button, 'scaleX'))).toBe(1)
      expect(Number(gsap.getProperty(button, 'scaleY'))).toBe(1)
    } finally {
      wrapper.unmount()
    }
  })

  it('still settles on the resting button when the transition runs to the end', async () => {
    // 对照组：不中断时，过渡走完必须回到正圆（复位不能破坏正常收尾）。
    vi.stubGlobal('matchMedia', () => mediaQuery(false))
    const wrapper = mountButton()
    const button = wrapper.get('button').element as HTMLButtonElement
    try {
      await wrapper.setProps({ actionMode: 'stop' })
      // 真实等待跨过整段过渡（约 0.32s），再推进一帧收尾。
      await new Promise((resolve) => setTimeout(resolve, 600))
      gsap.ticker.tick()
      expect(button.dataset.state).toBe('stop')
      expect(Number(gsap.getProperty(button, 'scaleX'))).toBe(1)
      expect(Number(gsap.getProperty(button, 'scaleY'))).toBe(1)
      expect(Number(gsap.getProperty(button, '--glyph-opacity'))).toBe(1)
      // 收尾后只剩位置微调（quickTo 写的 translate），不允许有缩放残留。
      expect(button.style.transform).not.toContain('scale')
    } finally {
      wrapper.unmount()
    }
  })
})
