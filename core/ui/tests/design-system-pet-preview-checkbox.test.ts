import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PetPreview from '../src/pet/ui/PetPreview.vue'
import UiSelect from '../src/components/UiSelect.vue'
vi.mock('../src/pet/render/threeLayer', () => ({ createThreePetLayer: vi.fn(async () => null) }))

describe('pet import preview checkboxes', () => {
  it('keeps debug toggles interactive and saves hitbox enablement on confirmation', async () => {
    const confirmImport = vi.fn(async () => {})
    const runtime = { importer: { analysis: { ok: true, name: '示例', actions: {}, manifest: {}, unsupported: [], warnings: [], errors: [] }, actionMapping: [], spriteWidth: 128, spriteHeight: 128, scale: 1 }, config: { quality: 'low' }, confirmImport, cancelImport: vi.fn() }
    const wrapper = mount(PetPreview, { props: { runtime: runtime as any } })
    await flushPromises()
    const debug = wrapper.findAll('input[type=checkbox]')
    expect(debug).toHaveLength(4)
    for (const input of debug) expect(input.classes()).toContain('sunday-checkbox')
    await debug[0].setValue(false)
    expect((debug[0].element as HTMLInputElement).checked).toBe(false)
    await wrapper.findAll('button').find(button => button.text() === '指定 Action')!.trigger('click')
    const previewAction = wrapper.get('[data-pet-preview-action]').getComponent(UiSelect)
    previewAction.vm.$emit('update:modelValue', 'walk')
    await wrapper.vm.$nextTick()
    expect(previewAction.props('modelValue')).toBe('walk')
    await wrapper.findAll('button').find(button => button.text() === 'Hitbox 编辑')!.trigger('click')
    const hitbox = wrapper.findAll('input[type=checkbox]')[0]
    expect(hitbox.classes()).toContain('sunday-checkbox')
    await hitbox.setValue(false)
    const action = wrapper.get('[data-pet-preview-hitbox-action]').getComponent(UiSelect)
    action.vm.$emit('update:modelValue', 'dance')
    const doubleAction = wrapper.get('[data-pet-preview-hitbox-double]').getComponent(UiSelect)
    doubleAction.vm.$emit('update:modelValue', 'jump')
    await wrapper.vm.$nextTick()
    await wrapper.findAll('button').find(button => button.text().includes('确认并添加'))!.trigger('click')
    expect(confirmImport).toHaveBeenCalledWith(expect.objectContaining({ hitboxes: expect.arrayContaining([expect.objectContaining({ enabled: false, action: 'dance', doubleAction: 'jump' })]) }))
    wrapper.unmount()
  })
})
