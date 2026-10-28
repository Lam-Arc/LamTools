import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import CoreSubmissionStatus from '../src/components/CoreSubmissionStatus.vue'
import type { CoreComposerSubmission } from '../src/composables/useCoreLiveComposerController'

// user:“做吧”+(发送状态保留正文、附件和恢复入口，队列操作支持键盘)。
describe('submission status acceptance', () => {
  it('renders each request identity, progress and attachment without losing the original body', async () => {
    const wrapper = mount(CoreSubmissionStatus, { props: { submissions: [
      { id: 'a', threadId: 'thread', text: 'original body', attachments: [{ type: 'attachment', attachment_id: 'file', filename: 'notes.txt' }], state: 'preparing', error: '' },
      { id: 'b', threadId: 'thread', text: 'second body', attachments: [], state: 'unknown', error: 'reply lost' },
    ] as CoreComposerSubmission[], canEdit: true } })
    expect(wrapper.text()).toContain('正在准备')
    expect(wrapper.text()).toContain('notes.txt')
    expect(wrapper.text()).toContain('接收结果待确认')
    expect(wrapper.get('[data-submission-id="b"]').text()).toContain('second body')
    await wrapper.get('[data-submission-retry="b"]').trigger('click')
    expect(wrapper.emitted('retry')).toEqual([['b']])
    expect(wrapper.find('[data-submission-edit="b"]').exists()).toBe(false)
  })

  it('keeps failures visible and never offers to overwrite a new draft', async () => {
    const wrapper = mount(CoreSubmissionStatus, { props: { submissions: [
      { id: 'failed', threadId: 'thread', text: 'recover me', attachments: [], state: 'failed', error: 'permission denied' },
    ] as CoreComposerSubmission[], canEdit: false } })
    expect(wrapper.text()).toContain('permission denied')
    expect(wrapper.find('[data-submission-edit]').exists()).toBe(false)
    await wrapper.setProps({ canEdit: true })
    await wrapper.get('[data-submission-edit="failed"]').trigger('click')
    expect(wrapper.emitted('edit')).toEqual([['failed']])
    wrapper.unmount()
  })

  it('reveals queue actions when keyboard focus enters the action group', () => {
    const source = readFileSync(resolve('src/components/CoreQueuedInputTray.vue'), 'utf8')
    expect(source).toContain('.core-queued-input-actions:focus-within')
  })
})
