import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import CoreSubmissionStatus from '../src/components/CoreSubmissionStatus.vue'
import type { CoreComposerSubmission } from '../src/composables/useCoreLiveComposerController'

// user:“这个东西它太丑了，它不太协调”+(发送状态收成输入栏上方的低透玻璃胶囊，
// 不再把整段正文铺成消息区里的大块卡片)。
// user:“这个胶囊淡入淡出”+(状态行出现和消失都走淡入淡出，不硬切)。
describe('submission status capsule acceptance', () => {
  it('renders a compact low-trans glass capsule with progress, body teaser and attachments', () => {
    const wrapper = mount(CoreSubmissionStatus, { props: { submissions: [
      { id: 'a', threadId: 'thread', text: 'original body', attachments: [{ type: 'attachment', attachment_id: 'file', filename: 'notes.txt' }], state: 'sending', error: '' },
      { id: 'b', threadId: 'thread', text: 'second body', attachments: [], state: 'unknown', error: 'reply lost' },
    ] as CoreComposerSubmission[], canEdit: true } })
    const first = wrapper.get('[data-submission-id="a"]')
    expect(first.classes()).toContain('optical-glass')
    expect(first.classes()).toContain('optical-glass--low-trans')
    // 一行正文预览，不再出现可以撑高的整段正文块。
    expect(first.text()).toContain('正在发送')
    expect(first.text()).toContain('original body')
    expect(first.find('.submission-status__body').exists()).toBe(false)
    expect(first.text()).toContain('1 个附件')
    expect(wrapper.get('[data-submission-id="b"]').text()).toContain('接收结果待确认')
    expect(wrapper.get('[data-submission-id="b"]').text()).toContain('reply lost')
    const source = readFileSync(resolve('src/components/CoreSubmissionStatus.vue'), 'utf8')
    // user:“长消息是自动省略后面的内容啊…用…”+(正文预览只占一行，胶囊自身限宽)。
    expect(source).toContain('text-overflow: ellipsis')
    expect(source).toContain('white-space: nowrap')
    expect(source).toContain('max-width: min(100%, 34rem)')
  })

  it('keeps failures recoverable and never offers to overwrite a new draft', async () => {
    const wrapper = mount(CoreSubmissionStatus, { props: { submissions: [
      { id: 'failed', threadId: 'thread', text: 'recover me', attachments: [], state: 'failed', error: 'permission denied' },
    ] as CoreComposerSubmission[], canEdit: false } })
    expect(wrapper.text()).toContain('permission denied')
    expect(wrapper.find('[data-submission-edit]').exists()).toBe(false)
    await wrapper.setProps({ canEdit: true })
    await wrapper.get('[data-submission-retry="failed"]').trigger('click')
    expect(wrapper.emitted('retry')).toEqual([['failed']])
    await wrapper.get('[data-submission-edit="failed"]').trigger('click')
    expect(wrapper.emitted('edit')).toEqual([['failed']])
    wrapper.unmount()
  })

  it('drops states that already have feedback elsewhere so the capsule never flashes a receipt', () => {
    const wrapper = mount(CoreSubmissionStatus, { props: { submissions: [
      { id: 'accepted', threadId: 'thread', text: 'a', attachments: [], state: 'accepted', error: '' },
      { id: 'queued', threadId: 'thread', text: 'b', attachments: [], state: 'queued', error: '' },
      { id: 'guided', threadId: 'thread', text: 'c', attachments: [], state: 'guided', error: '' },
    ] as CoreComposerSubmission[], canEdit: true } })
    expect(wrapper.find('[data-submission-id]').exists()).toBe(false)
    expect(wrapper.findAll('.submission-status')).toHaveLength(0)
    wrapper.unmount()
  })

  it('fades the capsule in and out and stops the spinner for reduced motion', () => {
    const source = readFileSync(resolve('src/components/CoreSubmissionStatus.vue'), 'utf8')
    expect(source).toContain('submission-status-enter-active')
    expect(source).toContain('submission-status-leave-active')
    expect(source).toContain('prefers-reduced-motion: reduce')
  })

  it('reveals queue actions when keyboard focus enters the action group', () => {
    const source = readFileSync(resolve('src/components/CoreQueuedInputTray.vue'), 'utf8')
    expect(source).toContain('.core-queued-input-actions:focus-within')
  })
})

describe('composer top mount acceptance', () => {
  // user:“只在上面拼接一个下方不是圆角的矩形，上边是圆角，宽度等于输入框宽度减去输入框圆角宽度”+(托盘挂在输入栏上方，本身不改变输入栏轮廓)。
  it('attaches a narrower top-rounded tab above the untouched composer', () => {
    const layout = readFileSync(resolve('src/styles/layout.css'), 'utf8')
    expect(layout).toContain('--composer-radius: 20px')
    expect(layout).toMatch(/\.composer-root--floating > \.composer-queue-panel-host \{[^}]*width: calc\(var\(--composer-full-width\) - var\(--composer-radius\) \* 2\)/)
    expect(layout).not.toContain(':has(.core-guidance-queue-panel) > .floating-composer')
    const tray = readFileSync(resolve('src/components/CoreQueuedInputTray.vue'), 'utf8')
    expect(tray).toContain('border-radius: var(--composer-radius) var(--composer-radius) 0 0')
  })

  // user:“你悬浮的胶囊应该在它的上方，它不存在时在输入栏的上方”+(胶囊和目标/排队托盘共用一个固定在输入栏上沿的挂载点)。
  it('mounts the status capsule above the goal and queue tray', () => {
    const app = readFileSync(resolve('src/app/LamToolsApp.vue'), 'utf8')
    const start = app.indexOf('<template #composer-queue-panel>')
    const end = app.indexOf('</template>', start)
    expect(start).toBeGreaterThan(-1)
    const panel = app.slice(start, end)
    const capsule = panel.indexOf('<CoreSubmissionStatus')
    const tray = panel.indexOf('<CoreQueuedInputTray')
    expect(capsule).toBeGreaterThan(-1)
    expect(tray).toBeGreaterThan(capsule)
  })
})
