import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CorePingEditor from '../src/components/CorePingEditor.vue'
import UiSelect from '../src/components/UiSelect.vue'
import { patchPingConfig } from '../src/pet/pingConfigRepository'

vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => {}) }))
vi.mock('../src/pet/configFile', () => ({ hasPetConfigAccess: () => true }))
vi.mock('../src/pet/pingConfigRepository', async (load) => {
  const actual = await load<typeof import('../src/pet/pingConfigRepository')>()
  const initial = actual.defaultPingConfig()
  return { ...actual, readPingConfig: vi.fn(async () => initial), patchPingConfig: vi.fn(async (patch) => ({ ...initial, ...patch })) }
})
vi.mock('../src/pet/bridge', () => ({ apiBase: vi.fn(async () => '') }))
vi.mock('../src/pet/agent/client', () => ({ createPetAgentClient: () => ({ listProjects: async () => [{ id: 'a', name: '甲' }, { id: 'b', name: '乙' }], listSessions: async (project: string) => [{ id: `${project}-session`, title: `${project} 会话` }], close: () => {} }) }))

describe('Ping shared checkboxes', () => {
  it('keeps each setting update when using the shared checkbox', async () => {
    const wrapper = mount(CorePingEditor, { global: { stubs: { PingCaptureSandbox: true } } })
    await flushPromises()
    const inputs = wrapper.findAll('input[type=checkbox]')
    expect(inputs).toHaveLength(4)
    for (const input of inputs) expect(input.classes()).toContain('sunday-checkbox')
    for (const input of inputs) await input.setValue(!(input.element as HTMLInputElement).checked)
    wrapper.unmount()
    await flushPromises()
    expect(patchPingConfig).toHaveBeenCalledWith(expect.objectContaining({ enabled: expect.any(Boolean), autoAttachScreenshot: expect.any(Boolean), autoPlaceSwitch: expect.any(Boolean), sectors: expect.any(Array) }))
  })
  it('keeps screen size and scaling previews selectable without saving settings', async () => {
    vi.mocked(patchPingConfig).mockClear()
    const wrapper = mount(CorePingEditor, { global: { stubs: { PingCaptureSandbox: true } } })
    await flushPromises()
    const size = wrapper.get('[data-ping-preview-size]').getComponent(UiSelect)
    const scale = wrapper.get('[data-ping-preview-scale]').getComponent(UiSelect)
    await size.get('button').trigger('click')
    await flushPromises()
    const square = Array.from(document.querySelectorAll('.ui-select-option')).find(el => el.textContent?.includes('方形')) as HTMLElement
    expect(square).toBeTruthy()
    square.click()
    scale.vm.$emit('update:modelValue', '150')
    await wrapper.vm.$nextTick()
    expect(size.props('modelValue')).toBe('square')
    expect(scale.props('modelValue')).toBe('150')
    expect(patchPingConfig).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('updates the selected action type and local action through shared selects', async () => {
    vi.mocked(patchPingConfig).mockClear()
    const wrapper = mount(CorePingEditor, { global: { stubs: { PingCaptureSandbox: true } } })
    await flushPromises()
    const kind = wrapper.get('[data-ping-kind]').getComponent(UiSelect)
    kind.vm.$emit('update:modelValue', kind.props('modelValue'))
    await wrapper.vm.$nextTick()
    expect(patchPingConfig).not.toHaveBeenCalled()
    kind.vm.$emit('update:modelValue', 'custom')
    await wrapper.vm.$nextTick()
    wrapper.get('[data-ping-action]').getComponent(UiSelect).vm.$emit('update:modelValue', 'settings')
    wrapper.unmount()
    await flushPromises()
    const patch = vi.mocked(patchPingConfig).mock.calls.at(-1)?.[0]
    expect(patch?.sectors).toEqual(expect.arrayContaining([expect.objectContaining({ kind: 'custom', action: 'settings' })]))
  })

  it('loads sessions for the selected project and keeps the target selector disabled when needed', async () => {
    const wrapper = mount(CorePingEditor, { global: { stubs: { PingCaptureSandbox: true } } })
    await flushPromises()
    const project = wrapper.get('[data-ping-project]').getComponent(UiSelect)
    project.vm.$emit('update:modelValue', 'b')
    await flushPromises()
    const session = wrapper.get('[data-ping-session]').getComponent(UiSelect)
    expect(project.props('modelValue')).toBe('b')
    expect(session.props('modelValue')).toBe('b-session')
    expect(session.props('options')).toEqual([{ value: 'b-session', label: 'b 会话' }])
    expect(session.props('disabled')).toBe(false)
    wrapper.unmount()
  })

  it('does not save when the current action type is selected again', async () => {
    vi.mocked(patchPingConfig).mockClear()
    const wrapper = mount(CorePingEditor, { global: { stubs: { PingCaptureSandbox: true } } })
    await flushPromises()
    const kind = wrapper.get('[data-ping-kind]').getComponent(UiSelect)
    kind.vm.$emit('update:modelValue', kind.props('modelValue'))
    wrapper.unmount()
    await flushPromises()
    expect(patchPingConfig).not.toHaveBeenCalled()
  })

})

