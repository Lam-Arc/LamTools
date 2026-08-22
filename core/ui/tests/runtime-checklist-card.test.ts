import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RuntimeChecklistCard from '../src/components/RuntimeChecklistCard.vue'
import type { CoreRuntimeStepGroup } from '../src/types'

const stepGroups: CoreRuntimeStepGroup[] = [{
  id: 'plan',
  label: 'Checklist',
  status: 'running',
  steps: [
    { id: 's1', title: '检查接线', status: 'completed', deliverables: ['接线记录'] },
    { id: 's2', title: '完成验证', status: 'running', deliverables: ['测试报告', '截图'] },
    { id: 's3', title: '整理交付', status: 'pending', deliverables: ['交付目录'] },
  ],
}]

describe('RuntimeChecklistCard', () => {
  it('shows the previous completed step and current deliverables in the compact view', () => {
    const wrapper = mount(RuntimeChecklistCard, { props: { stepGroups } })

    expect(wrapper.find('.runtime-checklist-card').exists()).toBe(true)
    expect(wrapper.find('.runtime-checklist-card__compact-title').text()).toBe('第 2：完成验证')
    expect(wrapper.find('.runtime-checklist-card__compact-row').text()).not.toContain('测试报告')
    expect(wrapper.find('.runtime-checklist-card__compact-row').text()).not.toContain('截图')
    expect(wrapper.find('.runtime-checklist-card__previous').exists()).toBe(false)
    expect(wrapper.find('.runtime-checklist-card__current').exists()).toBe(false)
    expect(wrapper.find('.runtime-checklist-card__details').isVisible()).toBe(false)
  })

  it('expands and collapses the complete plan with accessible state', async () => {
    const wrapper = mount(RuntimeChecklistCard, { props: { stepGroups } })
    const card = wrapper.get('.runtime-checklist-card')
    const detailsId = card.attributes('aria-controls')

    expect(card.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find(`#${detailsId}`).attributes('aria-hidden')).toBe('true')

    await card.trigger('click')
    expect(wrapper.get('.runtime-checklist-card').attributes('aria-expanded')).toBe('true')
    expect(wrapper.findAll('.runtime-checklist-card__step')).toHaveLength(3)
    expect(wrapper.find(`#${detailsId}`).attributes('aria-hidden')).toBe('false')
    await wrapper.get('.runtime-checklist-card__toggle').trigger('click')
    expect(wrapper.get('.runtime-checklist-card').attributes('aria-expanded')).toBe('false')
    expect(wrapper.find(`#${detailsId}`).attributes('aria-hidden')).toBe('true')
  })

  it('keeps a failed current step visible and uses current_step_id over multiple running steps', () => {
    const wrapper = mount(RuntimeChecklistCard, {
      props: {
        stepGroups: [{
          ...stepGroups[0],
          metadata: { current_step_id: 's3' },
          steps: [
            { ...stepGroups[0].steps[0] },
            { ...stepGroups[0].steps[1], status: 'running' as const },
            { ...stepGroups[0].steps[2], status: 'failed' as const },
          ],
        }],
      },
    })

    expect(wrapper.find('.runtime-checklist-card').exists()).toBe(true)
    expect(wrapper.find('.runtime-checklist-card__compact-title').text()).toContain('整理交付')
    expect(wrapper.find('.runtime-checklist-card__compact-row .runtime-checklist-card__status').text()).toBe('失败')
    expect(wrapper.find('.runtime-checklist-card__compact-row').classes()).not.toContain('is-running')
    expect(wrapper.find('.runtime-checklist-card__compact-row .runtime-checklist-card__indicator--running').exists()).toBe(false)
  })

  it('hides when the current turn has no running or failed step', () => {
    const wrapper = mount(RuntimeChecklistCard, {
      props: {
        stepGroups: [{ ...stepGroups[0], status: 'completed', steps: stepGroups[0].steps.map((step) => ({ ...step, status: 'completed' as const })) }],
      },
    })

    expect(wrapper.find('.runtime-checklist-card').exists()).toBe(false)
  })

  it('toggles from the keyboard without relying on a click-only interaction', async () => {
    const wrapper = mount(RuntimeChecklistCard, { props: { stepGroups } })
    const card = wrapper.get('.runtime-checklist-card')

    await card.trigger('keydown', { key: 'Enter' })
    expect(wrapper.get('.runtime-checklist-card').attributes('aria-expanded')).toBe('true')
    await wrapper.get('.runtime-checklist-card__toggle').trigger('keydown', { key: ' ' })
    expect(wrapper.get('.runtime-checklist-card').attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('.runtime-checklist-card__details').isVisible()).toBe(false)
  })
})
