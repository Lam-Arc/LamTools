import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RuntimePanel from '../src/components/RuntimePanel.vue'

describe('RuntimePanel', () => {
  it('does not render a process block without checklist steps', () => {
    const wrapper = mount(RuntimePanel, {
      props: {
        stepGroups: [{ id: 'core', label: 'Core', status: 'completed', steps: [] }],
      },
    })

    expect(wrapper.text()).not.toContain('过程')
    expect(wrapper.text()).not.toContain('Core')
  })

  it('keeps raw events hidden and shows a compact recent-step summary by default', async () => {
    const wrapper = mount(RuntimePanel, {
      props: {
        events: [{ id: 'event-1', type: 'core/runItem', timestamp: '', data: { raw: 'noisy payload' } }],
        stepGroups: [{
          id: 'core',
          label: 'Core',
          status: 'completed',
          steps: Array.from({ length: 5 }, (_, index) => ({
            id: `step-${index + 1}`,
            title: `步骤 ${index + 1}`,
            status: 'completed' as const,
          })),
        }],
      },
    })

    expect(wrapper.text()).not.toContain('noisy payload')
    expect(wrapper.text()).not.toContain('Events')
    expect(wrapper.findAll('.runtime-panel__step')).toHaveLength(3)
    expect(wrapper.text()).toContain('步骤 3')
    expect(wrapper.text()).toContain('步骤 5')

    await wrapper.get('.runtime-panel__more').trigger('click')
    expect(wrapper.findAll('.runtime-panel__step')).toHaveLength(5)
  })
})
