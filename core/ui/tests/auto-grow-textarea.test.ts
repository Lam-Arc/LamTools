import { describe, expect, it } from 'vitest'

import { autoGrowTextarea, TEXTAREA_MAX_ROWS } from '../src/helpers/autoGrowTextarea'

/** jsdom reports no layout, so the content height is what the test declares. */
function stubField(contentHeight: number, style: Partial<CSSStyleDeclaration> = {}): HTMLTextAreaElement {
  const field = document.createElement('textarea')
  Object.assign(field.style, { lineHeight: '20px', paddingTop: '8px', paddingBottom: '8px' }, style)
  document.body.appendChild(field)
  Object.defineProperty(field, 'scrollHeight', { configurable: true, value: contentHeight })
  return field
}

describe('autoGrowTextarea', () => {
  it('keeps a short answer at its content height', () => {
    const field = stubField(32)

    autoGrowTextarea(field)

    expect(field.style.height).toBe('32px')
    expect(field.style.overflowY).toBe('hidden')
  })

  it('grows with the answer and scrolls once it passes the row cap', () => {
    const field = stubField(700)

    autoGrowTextarea(field)

    const cap = 20 * TEXTAREA_MAX_ROWS + 16
    expect(field.style.height).toBe(`${cap}px`)
    expect(field.style.overflowY).toBe('auto')
  })

  it('shrinks back when the answer is cleared', () => {
    const field = stubField(700)
    autoGrowTextarea(field)

    Object.defineProperty(field, 'scrollHeight', { configurable: true, value: 20 })
    autoGrowTextarea(field)

    expect(field.style.height).toBe('20px')
    expect(field.style.overflowY).toBe('hidden')
  })

  it('measures with a fallback line height when the field declares none', () => {
    const field = stubField(700, { lineHeight: 'normal' })

    autoGrowTextarea(field)

    expect(field.style.height).toBe('116px')
  })

  it('ignores a field that is not mounted', () => {
    expect(() => autoGrowTextarea(null)).not.toThrow()
  })
})
