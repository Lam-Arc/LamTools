import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ThinkingIntensitySlider from '../src/components/ThinkingIntensitySlider.vue'

const wrappers: ReturnType<typeof mount>[] = []

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

const ladder = [
  { value: 'high', label: '高' },
  { value: 'off', label: '关闭' },
  { value: 'light', label: '轻' },
  { value: 'max', label: '极高' },
  { value: 'medium', label: '中' },
]

function fixture(modelValue = 'medium', options = ladder) {
  const wrapper = mount(ThinkingIntensitySlider, {
    props: { modelValue, options, label: '思考强度' },
  })
  wrappers.push(wrapper)
  return wrapper
}

describe('ThinkingIntensitySlider', () => {
  it('sorts an unsorted ladder low to high and exposes one vertical slider', () => {
    const wrapper = fixture()
    const rail = wrapper.get('[data-core-thinking-slider]')

    expect(rail.attributes('role')).toBe('slider')
    expect(rail.attributes('aria-orientation')).toBe('vertical')
    expect(rail.attributes('aria-valuemin')).toBe('0')
    expect(rail.attributes('aria-valuemax')).toBe('4')
    expect(rail.attributes('aria-valuenow')).toBe('2')
    expect(rail.attributes('aria-valuetext')).toBe('中')
    expect(wrapper.findAll('[data-model-thinking-level-option]')).toHaveLength(5)
  })

  it('moves by keyboard and by direct level selection without closing', async () => {
    const wrapper = fixture()
    const rail = wrapper.get('[data-core-thinking-slider]')

    await rail.trigger('keydown', { key: 'ArrowUp' })
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([['high']])

    await rail.trigger('keydown', { key: 'End' })
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['max'])

    await wrapper.get('[data-model-thinking-level-option="light"]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['light'])
  })

  it('starts dragging from a tick so the knob centre is not stolen by the click target', async () => {
    const wrapper = fixture()
    await wrapper.get('[data-model-thinking-level-option="light"]').trigger('pointerdown')
    expect(wrapper.classes()).toContain('is-dragging')
    await wrapper.get('[data-model-thinking-level-option="light"]').trigger('pointerup')
    expect(wrapper.classes()).not.toContain('is-dragging')
  })

  it('shows six fading white dots inside the track only at max', async () => {
    const wrapper = fixture('max')
    expect(wrapper.find('.sunday-thinking-slider__max-dots').exists()).toBe(true)
    expect(wrapper.findAll('.sunday-thinking-slider__max-dot')).toHaveLength(6)

    await wrapper.setProps({ modelValue: 'high' })
    expect(wrapper.find('.sunday-thinking-slider__max-dots').exists()).toBe(false)
  })

  it('locks to the single available level', () => {
    const wrapper = fixture('off', [{ value: 'off', label: '关闭' }])
    const rail = wrapper.get('[data-core-thinking-slider]')

    expect(rail.attributes('aria-disabled')).toBe('true')
    expect(rail.attributes('tabindex')).toBe('-1')
    expect(wrapper.findAll('[data-model-thinking-level-option]')).toHaveLength(1)
  })
})
