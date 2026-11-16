import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import HumanTaskPanel from '../../src/lamtools_core/plugins/bundled/workflow/ui/HumanTaskPanel.vue'
import WorkflowNodeRuntimeDock from '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeRuntimeDock.vue'

// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(工作流两处加载状态共用旋转样式并保留速度)。
describe('workflow shared loading', () => {
  it('only spins the refresh and runtime icons while loading', async () => {
    const task = mount(HumanTaskPanel, { props: { loading: true } })
    const dock = mount(WorkflowNodeRuntimeDock, { props: { nodeId: 'n', title: '节点', kind: 'script', state: 'running' } })
    expect(task.find('.sunday-spin.sunday-spin--fast').exists()).toBe(true)
    expect(dock.find('.sunday-spin.sunday-spin--fast').exists()).toBe(true)
    await task.setProps({ loading: false })
    await dock.setProps({ state: 'error' })
    expect(task.find('.sunday-spin').exists()).toBe(false)
    expect(dock.find('.sunday-spin').exists()).toBe(false)
    task.unmount(); dock.unmount()
  })
})
