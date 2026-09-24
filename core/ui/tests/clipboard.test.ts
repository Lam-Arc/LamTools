import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyText } from '../src/helpers/clipboard'

const originalExecCommand = Object.getOwnPropertyDescriptor(document, 'execCommand')

afterEach(() => {
  vi.unstubAllGlobals()
  if (originalExecCommand) Object.defineProperty(document, 'execCommand', originalExecCommand)
  else Reflect.deleteProperty(document, 'execCommand')
})

describe('copyText', () => {
  it('falls back to selection copy when WebView denies Clipboard API access', async () => {
    const writeText = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    const execCommand = vi.fn().mockImplementation((command: string) => {
      expect(command).toBe('copy')
      expect(document.querySelector<HTMLTextAreaElement>('textarea[readonly]')?.value).toBe('copy me')
      return true
    })
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })

    await expect(copyText('copy me')).resolves.toBeUndefined()
    expect(writeText).toHaveBeenCalledWith('copy me')
    expect(execCommand).toHaveBeenCalledOnce()
    expect(document.querySelector('textarea[readonly]')).toBeNull()
  })

  it('reports failure when both copy paths fail', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
    Object.defineProperty(document, 'execCommand', { configurable: true, value: vi.fn().mockReturnValue(false) })

    await expect(copyText('copy me')).rejects.toThrow('复制失败')
    expect(document.querySelector('textarea[readonly]')).toBeNull()
  })
})
