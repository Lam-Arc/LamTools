import { nextTick } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  CORE_COMPOSER_ATTACHMENTS_PREFIX,
  usePendingAttachments,
} from '../src/composables/usePendingAttachments'
import type { CoreAttachment } from '../src/types'

function uploaded(id: string, filename = `${id}.txt`): CoreAttachment {
  return {
    id,
    filename,
    label: filename,
    mime_type: 'text/plain',
    size: 12,
    preview_type: 'text',
    status: 'uploaded',
  }
}

describe('usePendingAttachments per-session tray', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('parks the outgoing session tray and restores each session independently', async () => {
    const tray = usePendingAttachments()
    tray.setSession('thread-a')
    tray.addUploaded(uploaded('att-a'))
    await nextTick()

    tray.setSession('thread-b')
    tray.addUploaded(uploaded('att-b'))
    await nextTick()

    tray.setSession('thread-a')
    expect(tray.pendingAttachments.value.map(item => item.id)).toEqual(['att-a'])

    tray.setSession('thread-b')
    expect(tray.pendingAttachments.value.map(item => item.id)).toEqual(['att-b'])
  })

  it('restores only uploaded attachments after a restart', async () => {
    const tray = usePendingAttachments()
    tray.setSession('thread-c')
    tray.addUploaded(uploaded('att-uploaded'))
    tray.addProcessing('att-uploading', 'large.bin', 'C:/large.bin')
    tray.markFailed('att-failed', 'bad.bin', 'boom')
    await nextTick()

    const restarted = usePendingAttachments()
    restarted.setSession('thread-c')

    expect(restarted.pendingAttachments.value).toEqual([
      expect.objectContaining({ id: 'att-uploaded', status: 'uploaded' }),
    ])
  })

  it('drops the stored tray when the composer send clears attachments', async () => {
    const tray = usePendingAttachments()
    tray.setSession('thread-d')
    tray.addUploaded(uploaded('att-d'))
    await nextTick()
    expect(window.localStorage.getItem(`${CORE_COMPOSER_ATTACHMENTS_PREFIX}thread-d`)).not.toBeNull()

    tray.clearAttachments()
    await nextTick()

    expect(window.localStorage.getItem(`${CORE_COMPOSER_ATTACHMENTS_PREFIX}thread-d`)).toBeNull()
  })
})
