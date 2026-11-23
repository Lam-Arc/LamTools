import { beforeEach, describe, expect, it, vi } from 'vitest'

// user:“非交互区域均可拖拽”+(标题带空白处拖窗；按钮/输入/标签页等交互件不触发)。
const tauri = vi.hoisted(() => ({ inTauri: true, startDragging: vi.fn(async () => undefined) }))

vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => tauri.inTauri }))
vi.mock('@tauri-apps/api/window', () => ({ getCurrentWindow: () => ({ startDragging: tauri.startDragging }) }))

import { startWindowDragFromBlank } from '../src/composables/useWindowDrag'

function pointerdown(target: Element): PointerEvent {
  const event = new PointerEvent('pointerdown', { bubbles: true, button: 0, cancelable: true })
  target.dispatchEvent(event)
  return event
}

beforeEach(() => {
  tauri.inTauri = true
  tauri.startDragging.mockClear()
})

describe('startWindowDragFromBlank', () => {
  it('drags from a blank band area', () => {
    const band = document.createElement('div')
    const spacer = document.createElement('span')
    band.appendChild(spacer)
    band.addEventListener('pointerdown', startWindowDragFromBlank)
    document.body.appendChild(band)

    const event = pointerdown(spacer)

    expect(tauri.startDragging).toHaveBeenCalledTimes(1)
    // 拖窗时把默认行为拦掉，免得顺手把标题文字拖成选区。
    expect(event.defaultPrevented).toBe(true)
    band.remove()
  })

  it('leaves interactive controls alone', () => {
    const band = document.createElement('div')
    const button = document.createElement('button')
    const input = document.createElement('input')
    band.append(button, input)
    band.addEventListener('pointerdown', startWindowDragFromBlank)
    document.body.appendChild(band)

    pointerdown(button)
    pointerdown(input)

    expect(tauri.startDragging).not.toHaveBeenCalled()
    band.remove()
  })

  it('does nothing outside Tauri', () => {
    tauri.inTauri = false
    const band = document.createElement('div')
    band.addEventListener('pointerdown', startWindowDragFromBlank)
    document.body.appendChild(band)

    pointerdown(band)

    expect(tauri.startDragging).not.toHaveBeenCalled()
    band.remove()
  })
})
