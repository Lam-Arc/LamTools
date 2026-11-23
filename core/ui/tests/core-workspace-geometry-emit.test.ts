import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import CoreWorkspace from '../src/components/CoreWorkspace.vue'
import { useWorkspace } from '../src/workspace/useWorkspace'

/**
 * user:“会话无法显示了，排查一下”+
 * (先写验收测试：分屏恢复时先以 0x0 挂载 CoreWorkspace，随后 measure()/ResizeObserver
 *  传入真实窗口尺寸，watch 必须重新 emit 有效的 --split-primary-width/height/visible，
 *  不能因为把 rect 对象 .join('|') 成 "[object Object]" 而永不触发，导致主聊天区一直 0x0 隐藏。)
 */
describe('CoreWorkspace geometry emission after mount', () => {
  it('emits updated --split-primary-* styles when bounds change from 0x0 to real viewport and resize', async () => {
    const controller = useWorkspace(ref('test.workspace.emit'), ref('/root'), ref(null), { persist: false })
    controller.split('main', 'right')

    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '/root' },
    })
    await nextTick()

    controller.setBounds({ x: 0, y: 0, width: 1000, height: 600 })
    await nextTick()

    const emitted = wrapper.emitted('geometry') ?? []
    expect(emitted.length).toBeGreaterThan(0)
    const latest = emitted.at(-1)?.[0] as Record<string, string>
    expect(Number.parseInt(latest['--split-primary-width'], 10)).toBeGreaterThan(0)
    expect(latest['--split-primary-height']).toBe('600px')
    expect(latest['--split-primary-visible']).toBe('visible')

    controller.setBounds({ x: 0, y: 0, width: 1200, height: 700 })
    await nextTick()

    const resized = (wrapper.emitted('geometry') ?? []).at(-1)?.[0] as Record<string, string>
    expect(Number.parseInt(resized['--split-primary-width'], 10)).toBeGreaterThan(
      Number.parseInt(latest['--split-primary-width'], 10),
    )
    expect(resized['--split-primary-height']).toBe('700px')
    expect(resized['--split-primary-visible']).toBe('visible')

    wrapper.unmount()
  })
})
