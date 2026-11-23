import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import CaptureApp from '../src/pet/ui/CaptureApp.vue'
import CaptureEditor from '../src/pet/ui/CaptureEditor.vue'

const mocks = vi.hoisted(() => ({ closeWindow: vi.fn(async () => {}), closeClient: vi.fn(), send: vi.fn(), upload: vi.fn() }))
vi.mock('../src/pet/bridge', () => ({ showPingCapture: vi.fn(async () => {}), heartbeatPingCapture: vi.fn(async () => {}), closePingCapture: mocks.closeWindow, readConfigText: vi.fn(async () => null), apiBase: vi.fn(async () => 'http://127.0.0.1') }))
vi.mock('../src/pet/agent/client', () => ({ createPetAgentClient: () => ({ uploadScreenshot: mocks.upload, close: mocks.closeClient, attachmentInput: vi.fn() }) }))
vi.mock('../src/pet/agent/host', () => ({ PetAgentHost: class { async pingTarget() { return { projectId: 'p', sessionId: 's' } } channel() { return { sessionId: 's', projectId: 'p', send: mocks.send } } } }))

// user:“任何步骤按 Esc 都可以安全退出”+(上传中取消后不再发送消息或重复关闭客户端)。
it('does not send after Escape during upload', async () => {
  let finish!: (value: unknown) => void
  mocks.upload.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const frame = { width: 2, height: 2, scale: 1, data: new Uint8Array(16) }
  const wrapper = mount(CaptureApp, { props: { frame: frame as any, bootError: '' }, global: { stubs: { CaptureEditor: true } } })
  wrapper.findComponent(CaptureEditor).vm.$emit('send', { blob: new Blob(), text: '', meta: { x: 0, y: 0, width: 2, height: 2, scale: 1 } })
  await flushPromises()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await flushPromises()
  finish({ id: 'sample' }); await flushPromises()
  expect(mocks.closeWindow).toHaveBeenCalledOnce()
  expect(mocks.closeClient).toHaveBeenCalledOnce()
  expect(mocks.send).not.toHaveBeenCalled()
  wrapper.unmount()
})
