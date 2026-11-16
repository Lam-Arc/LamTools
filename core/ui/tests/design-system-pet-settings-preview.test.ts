import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CorePetEditor from '../src/components/CorePetEditor.vue'
import { patchPetConfig, readPetConfig, updatePetConfig } from '../src/pet/configFile'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
vi.mock('../src/pet/configFile.ts', () => ({ hasPetConfigAccess: () => false, readPetConfig: vi.fn(), patchPetConfig: vi.fn(), updatePetConfig: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn() }))
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })
describe('pet settings preview isolation', () => {
  it('renders the production controls and keeps edits in local state', async () => {
    vi.useFakeTimers()
    const wrapper = mount(CorePetEditor, { props: { preview: true }, global: { stubs: { Teleport: true } } }); await flushPromises()
    const enabled = wrapper.findAll('label.pet-settings-row').find(row => row.text().includes('启用桌宠'))!.get('input')
    await enabled.setValue(!(enabled.element as HTMLInputElement).checked)
    const sector = wrapper.get('.pet-settings-sector-label')
    await sector.setValue('本地预览'); await sector.trigger('change')
    const row = wrapper.findAll('.pet-settings-row').find(item => item.text().includes('真实遮挡模式'))!
    await row.get('.ui-select-trigger').trigger('click')
    await wrapper.findAll('.ui-select-option').find(option => option.text().includes('按窗口几何裁剪'))!.trigger('click')
    await vi.advanceTimersByTimeAsync(400); await flushPromises()
    expect((sector.element as HTMLInputElement).value).toBe('本地预览')
    expect(readPetConfig).not.toHaveBeenCalled()
    expect(patchPetConfig).not.toHaveBeenCalled()
    expect(updatePetConfig).not.toHaveBeenCalled()
    expect(invoke).not.toHaveBeenCalled()
    expect(listen).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
