import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AttachmentTray from '../src/components/AttachmentTray.vue'
import { contextMenuState, closeContextMenu } from '../src/components/context-menu/context-menu'
import { createFakeTransport } from './fake-transport'
import type { CoreAttachment } from '../src/types'

// user:“确保视觉、功能和交互不退化”+(上传中的附件不可从右键绕过不可预览状态)。
describe('attachment context menu states', () => {
  afterEach(closeContextMenu)
  it.each([
    ['uploading', ['remove']], ['failed', ['retry', 'remove']], ['uploaded', ['preview', 'open', 'remove']],
  ] as const)('offers only available actions while %s', async (status, expected) => {
    const item: CoreAttachment = { id: 'file', filename: 'file.txt', mime_type: 'text/plain', size: 1, preview_type: 'text', status }
    const wrapper = mount(AttachmentTray, { props: { attachments: [item], transport: createFakeTransport() } })
    await wrapper.get('.attachment-entry').trigger('contextmenu')
    expect(contextMenuState.items.filter(entry => entry.type !== 'separator').map(entry => entry.id)).toEqual(expected)
    wrapper.unmount()
  })
})
