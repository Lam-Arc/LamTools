// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// user:“确保视觉、功能和交互不退化”+(工作流标签继续经过保存／放弃／取消保护)。
describe('workflow title tab integration', () => {
  it('wires manual keyboard navigation without bypassing the existing switch guard', () => {
    const source = readFileSync('../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowView.vue', 'utf8')
    expect(source).toContain('@keydown="onManualTabGroupKeydown"')
    expect(source).toContain('@click="selectWorkflow(tab.id)"')
    expect(source).toContain('<WorkflowSwitchGuard :open="Boolean(workflowSwitchGuard)" @choice="resolveWorkflowSwitch" />')
    expect(source).toContain('const switchChoice = await requestWorkflowSwitch(workflowId)')
    expect(source).toContain("if (switchChoice === 'cancel') return")
    expect(source).toContain('@keydown.enter.stop.prevent="closeWorkflowTab(tab.id)"')
  })
})
