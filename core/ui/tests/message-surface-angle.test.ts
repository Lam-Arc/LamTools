import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import CoreMessageSurface from '../src/components/CoreMessageSurface.vue'
import { messageSurfaceEdgeAngle } from '../src/helpers/messageSurfaceAngle'

/**
 * user:“按对角线”+(玻璃边的角度按元素宽高算，不再固定 45°)。
 */
describe('messageSurfaceEdgeAngle', () => {
  it('uses the box diagonal: atan2(width, height)', () => {
    expect(messageSurfaceEdgeAngle(100, 100)).toBeCloseTo(45, 5)
    expect(messageSurfaceEdgeAngle(400, 60)).toBeCloseTo(81.47, 1)
    expect(messageSurfaceEdgeAngle(60, 400)).toBeCloseTo(8.53, 1)
  })

  it('falls back to 45deg before layout', () => {
    expect(messageSurfaceEdgeAngle(0, 0)).toBe(45)
    expect(messageSurfaceEdgeAngle(Number.NaN, 60)).toBe(45)
  })

  it('writes the measured angle into the surface CSS variable', () => {
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 400,
      height: 60,
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 400,
      bottom: 60,
      toJSON: () => ({}),
    } as DOMRect)
    const wrapper = mount(CoreMessageSurface)
    expect(wrapper.get('.message-surface').attributes('style')).toContain('--message-surface-edge-angle: 81.47deg')
    wrapper.unmount()
    spy.mockRestore()
  })
})
