import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import RuntimeChecklistCard from '../src/components/RuntimeChecklistCard.vue'
import RightSidebarChecklist from '../src/components/RightSidebarChecklist.vue'
import { setUiLanguage } from '../src/i18n/index.ts'
import type { CoreRuntimeStepGroup } from '../src/types.ts'

afterEach(() => setUiLanguage('zh-CN'))
describe('task status labels', () => {
  it('updates both real views when the interface language changes', async () => {
    const stepGroups: CoreRuntimeStepGroup[] = [{ id: 'g', label: 'Group', status: 'running', steps: [
      { id: 'a', title: 'A', status: 'pending' }, { id: 'b', title: 'B', status: 'running' },
      { id: 'c', title: 'C', status: 'completed' }, { id: 'd', title: 'D', status: 'failed' }, { id: 'e', title: 'E', status: 'skipped' },
    ] }]
    const card = mount(RuntimeChecklistCard, { props: { stepGroups } })
    const sidebar = mount(RightSidebarChecklist, { props: { stepGroups } })
    await card.get('.runtime-checklist-card').trigger('click')
    expect(card.text()).toContain('运行中')
    expect(sidebar.text()).toContain('运行中')
    setUiLanguage('en')
    await card.vm.$nextTick()
    for (const label of ['Pending', 'Running', 'Completed', 'Failed', 'Skipped']) {
      expect(card.text()).toContain(label)
      expect(sidebar.text()).toContain(label)
    }
    setUiLanguage('zh-TW')
    await card.vm.$nextTick()
    expect(card.text()).toContain('執行中')
    expect(sidebar.text()).toContain('執行中')
    card.unmount(); sidebar.unmount()
  })
})
