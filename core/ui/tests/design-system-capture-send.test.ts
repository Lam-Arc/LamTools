import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import CaptureEditor from '../src/pet/ui/CaptureEditor.vue'

// user:“确保视觉、功能和交互不退化”+(图片生成期间不能重复发送)。
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('blocks duplicate sends while the image is being encoded', async () => {
  const context = { putImageData: vi.fn(), drawImage: vi.fn(), save: vi.fn(), translate: vi.fn(), restore: vi.fn() }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as any)
  let finish!: (blob: Blob | null) => void
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => { finish = callback })
  vi.stubGlobal('ImageData', class { constructor(..._args: unknown[]) {} })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const frame = { width: 2, height: 2, scale: 1, data: new Uint8Array(16) }
  const onSend = vi.fn()
  const wrapper = mount(CaptureEditor, { props: { frame: frame as any, sandbox: true, busy: false, error: '', onSend } }); await flushPromises()
  const send = wrapper.get('[aria-label="发送"]')
  await send.trigger('click'); await send.trigger('click')
  expect(HTMLCanvasElement.prototype.toBlob).toHaveBeenCalledTimes(1)
  finish(new Blob(['sample'], { type: 'image/png' })); await flushPromises()
  expect(onSend).toHaveBeenCalledTimes(1)
  await wrapper.get('[aria-label="发送"]').trigger('click')
  wrapper.unmount()
  finish(new Blob(['late'], { type: 'image/png' })); await flushPromises()
  expect(onSend).toHaveBeenCalledTimes(1)
})
