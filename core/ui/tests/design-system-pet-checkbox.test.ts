import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CorePetEditor from '../src/components/CorePetEditor.vue'
import { defaultConfig } from '../src/pet/config'
import { patchPetConfig } from '../src/pet/configFile'

vi.mock('../src/pet/configFile.ts', () => ({ hasPetConfigAccess: () => true, readPetConfig: vi.fn(async () => null), patchPetConfig: vi.fn(async () => {}), updatePetConfig: vi.fn(async () => {}) }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn(async () => {}) }))
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => {}) }))
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('pet settings shared checkboxes', () => {
  it('keeps separate immediate and debounced persistence', async () => {
    const wrapper = mount(CorePetEditor)
    await flushPromises()
    const labels = wrapper.findAll('label.pet-settings-row')
    const enabled = labels.find(label => label.text().includes('启用桌宠'))!.get('input.sunday-checkbox')
    const l3 = labels.find(label => label.text().includes('L3 视觉边缘识别'))!.get('input.sunday-checkbox')
    const screenshot = labels.find(label => label.text().includes('自动附当前截图'))!.get('input.sunday-checkbox')
    await enabled.setValue(!defaultConfig().enabled)
    await flushPromises()
    expect(patchPetConfig).toHaveBeenCalledWith({ enabled: !defaultConfig().enabled })
    vi.useFakeTimers()
    await l3.setValue(true)
    await screenshot.setValue(!defaultConfig().ping.autoAttachScreenshot)
    await vi.advanceTimersByTimeAsync(300)
    expect(patchPetConfig).toHaveBeenCalledWith({ useL3: true, ping: { autoAttachScreenshot: !defaultConfig().ping.autoAttachScreenshot } })
    wrapper.unmount()
  })
  it('keeps pet geometry, quality and notification selections with shared menus', async () => {
    const wrapper = mount(CorePetEditor, { global: { stubs: { Teleport: true } } })
    await flushPromises()
    vi.useFakeTimers()
    for (const [label, text] of [['真实遮挡模式', '置顶 + 按窗口几何裁剪（推荐）'], ['几何精度', '高（更贴边缘）'], ['Agent 提问', '静默']]) {
      const row = wrapper.findAll('.pet-settings-row').find(item => item.text().includes(label))!
      await row.get('.ui-select-trigger').trigger('click')
      const option = row.findAll('.ui-select-option').find(item => item.text() === text)!
      await option.trigger('click')
    }
    await vi.advanceTimersByTimeAsync(300)
    expect(patchPetConfig).toHaveBeenCalledWith(expect.objectContaining({ zMode: 'clip', quality: 'high', bubbles: { question: 'silent' } }))
    wrapper.unmount()
  })

})
