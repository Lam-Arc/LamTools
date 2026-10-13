import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ComposerBar from '../src/components/ComposerBar.vue'
import CoreSubAgentActivityIndicator from '../src/components/CoreSubAgentActivityIndicator.vue'

describe('CoreSubAgentActivityIndicator', () => {
  it('stays laid out but hidden while no sub-agent is running', () => {
    const wrapper = mount(CoreSubAgentActivityIndicator, { props: { active: false, names: ['worker'] } })
    const root = wrapper.find('[data-sub-agent-activity]')
    expect(root.exists()).toBe(true)
    // Kept in the toolbar so appearing/disappearing cannot push the neighbours.
    expect(root.classes()).not.toContain('sub-agent-activity--active')
    wrapper.unmount()
  })

  it('shows the pulse and names the running sub-agents when active', () => {
    const wrapper = mount(CoreSubAgentActivityIndicator, { props: { active: true, names: ['renderer_dev', 'sim_tester'] } })
    const root = wrapper.find('[data-sub-agent-activity]')
    expect(root.classes()).toContain('sub-agent-activity--active')
    expect(root.attributes('aria-label')).toBe('子代理运行中：renderer_dev、sim_tester')
    wrapper.unmount()
  })

  it('falls back to a generic label without names', () => {
    const wrapper = mount(CoreSubAgentActivityIndicator, { props: { active: true } })
    expect(wrapper.find('[data-sub-agent-activity]').attributes('aria-label')).toBe('子代理运行中')
    wrapper.unmount()
  })

  it('scopes the pulse to the active state so it does not animate in the background', () => {
    const source = readFileSync(resolve(import.meta.dirname, '../src/components/CoreSubAgentActivityIndicator.vue'), 'utf8')
    // The keyframe is referenced only from the active selector.
    const animationUses = source.match(/animation:\s*sub-agent-activity-breathe/g) ?? []
    expect(animationUses).toHaveLength(1)
    expect(source).toContain('.sub-agent-activity--active .sub-agent-activity-icon')
    // Reduced motion still turns it off.
    expect(source).toContain('prefers-reduced-motion')
  })
})

describe('ComposerBar extras placement', () => {
  it('keeps delegated-work activity in the toolbar instead of a bottom composer notice', () => {
    const appSource = readFileSync(resolve(import.meta.dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(appSource).toMatch(/<template #runtime-indicator>[\s\S]*?<CoreSubAgentActivityIndicator[\s\S]*?<\/template>/)
    expect(appSource).not.toContain('#composer-extras')
  })

  it('renders the extras slot after the floating form, not inside it', async () => {
    const wrapper = mount(ComposerBar, {
      props: { variant: 'floating' },
      slots: { extras: () => h('span', { 'data-below-composer': '' }, 'notice') },
    })
    await nextTick()

    const host = wrapper.element as HTMLElement
    const extras = host.querySelector('.composer-extras')
    const form = host.querySelector('form.floating-composer')
    expect(extras).toBeTruthy()
    expect(form).toBeTruthy()
    // Below the composer card, and a sibling of the form so it never changes
    // the card's own box.
    expect(form!.contains(extras!)).toBe(false)
    expect(extras!.parentElement).toBe(host)
    expect(extras!.querySelector('[data-below-composer]')).toBeTruthy()
    wrapper.unmount()
  })

  it('renders no extras container when the slot is unused', () => {
    const wrapper = mount(ComposerBar, { props: { variant: 'floating' } })
    expect((wrapper.element as HTMLElement).querySelector('.composer-extras')).toBeNull()
    wrapper.unmount()
  })
})
