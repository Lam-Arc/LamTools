import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CoreGeneralEditor from '../src/components/CoreGeneralEditor.vue'
import {
  ASSISTANT_DISPLAY_DEFAULTS,
  setAssistantDisplayPreferences,
} from '../src/composables/useAssistantDisplayPreferences'

/**
 * user:“助手头像那块别填链接 上传，裁切”+(头像入口不再是图片地址输入框：
 * 选本地图片 → 拖动/缩放裁切 → 应用后把裁成正方形的头像直接存进显示偏好)
 */
describe('CoreGeneralEditor assistant avatar upload', () => {
  let storedAvatar = ''
  let storedSize: number | undefined
  let storedRoundness: number | undefined
  let rpc: ReturnType<typeof vi.fn>

  function createRpc() {
    return vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
      if (method === 'settings.get') {
        if (params.namespace === 'core.assistantDisplay') {
          return {
            namespace: params.namespace,
            value: {
              ...(storedAvatar ? { avatar: storedAvatar } : {}),
              ...(storedSize !== undefined ? { avatarSize: storedSize } : {}),
              ...(storedRoundness !== undefined ? { avatarRoundness: storedRoundness } : {}),
            },
          }
        }
        return { namespace: params.namespace, value: {} }
      }
      if (method === 'settings.update') {
        const value = (params.value || {}) as Record<string, unknown>
        if (params.namespace === 'core.assistantDisplay') {
          if (typeof value.avatar === 'string') storedAvatar = value.avatar
          if (typeof value.avatarSize === 'number') storedSize = value.avatarSize
          if (typeof value.avatarRoundness === 'number') storedRoundness = value.avatarRoundness
        }
        return { namespace: params.namespace, value }
      }
      return {}
    })
  }

  beforeEach(() => {
    localStorage.clear()
    storedAvatar = ''
    storedSize = undefined
    storedRoundness = undefined
    setAssistantDisplayPreferences(ASSISTANT_DISPLAY_DEFAULTS)
    rpc = createRpc()

    // jsdom 没有图片解码和 canvas：用固定的原图尺寸 + 假画布跑完整个上传流程。
    class FakeImage {
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      naturalWidth = 800
      naturalHeight = 400
      width = 800
      height = 400
      set src(_value: string) {
        queueMicrotask(() => this.onload?.())
      }
    }
    vi.stubGlobal('Image', FakeImage)
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/webp;base64,cropped-avatar')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    localStorage.clear()
    setAssistantDisplayPreferences(ASSISTANT_DISPLAY_DEFAULTS)
  })

  async function settle(rounds = 6): Promise<void> {
    for (let i = 0; i < rounds; i += 1) {
      await flushPromises()
      await new Promise((resolve) => setTimeout(resolve, 0))
    }
  }

  async function mountEditor() {
    const wrapper = mount(CoreGeneralEditor, { props: { requestRpc: rpc } })
    await settle()
    return wrapper
  }

  async function pickImage(wrapper: ReturnType<typeof mount>) {
    const fileInput = wrapper.get('[data-avatar-file]').element as HTMLInputElement
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'avatar.png', { type: 'image/png' })
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
    await wrapper.get('[data-avatar-file]').trigger('change')
    await settle()
  }

  it('replaces the image-address input with an upload entry', async () => {
    const wrapper = await mountEditor()

    expect(wrapper.find('input[aria-label="头像"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('上传一张图片并调整裁切')
    expect(wrapper.find('[data-avatar-pick]').text()).toBe('上传图片')
    wrapper.unmount()
  })

  it('crops the picked image and saves the square result right away', async () => {
    const wrapper = await mountEditor()
    await pickImage(wrapper)

    expect(wrapper.find('[data-avatar-crop]').exists()).toBe(true)
    const apply = wrapper.get('[data-avatar-apply]')
    expect(apply.attributes('disabled')).toBeUndefined()
    await apply.trigger('click')
    await settle()

    expect(rpc).toHaveBeenCalledWith('settings.update', expect.objectContaining({
      namespace: 'core.assistantDisplay',
      value: expect.objectContaining({ avatar: 'data:image/webp;base64,cropped-avatar' }),
    }))
    expect(storedAvatar).toBe('data:image/webp;base64,cropped-avatar')
    expect(wrapper.find('[data-avatar-crop]').exists()).toBe(false)
    expect(wrapper.get('[data-avatar-pick]').text()).toBe('更换图片')
    wrapper.unmount()
  })

  it('removes the stored avatar from the same row', async () => {
    storedAvatar = 'data:image/png;base64,old-avatar'
    const wrapper = await mountEditor()

    expect(wrapper.find('[data-avatar-remove]').exists()).toBe(true)
    await wrapper.get('[data-avatar-remove]').trigger('click')
    await settle()

    expect(storedAvatar).toBe('')
    expect(wrapper.find('[data-avatar-remove]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('refuses a file that is not an image', async () => {
    const wrapper = await mountEditor()
    const fileInput = wrapper.get('[data-avatar-file]').element as HTMLInputElement
    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' })
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
    await wrapper.get('[data-avatar-file]').trigger('change')
    await settle()

    expect(wrapper.text()).toContain('请选择图片文件')
    expect(wrapper.find('[data-avatar-crop]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('persists the adjustable avatar size and roundness', async () => {
    const wrapper = await mountEditor()

    await wrapper.get('input[aria-label="头像大小"]').setValue('48')
    await wrapper.get('input[aria-label="圆角率"]').setValue('40')
    // 滑块停手后合并保存一次，等防抖窗口过去
    await new Promise((resolve) => setTimeout(resolve, 500))
    await settle()

    expect(storedSize).toBe(48)
    expect(storedRoundness).toBe(40)
    expect(rpc).toHaveBeenCalledWith('settings.update', expect.objectContaining({
      namespace: 'core.assistantDisplay',
      value: expect.objectContaining({ avatarSize: 48, avatarRoundness: 40 }),
    }))
    wrapper.unmount()
  })
})
