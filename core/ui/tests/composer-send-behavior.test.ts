import { describe, expect, it } from 'vitest'
import { coreComposerSendIntent } from '../src'

// user:“设置中可调消息发送后直接引导或排队，默认直接引导，默认为enter，特殊发送为ctrl enter”
// +(发送键在回合运行中按设置决定“直接引导”还是“排队”，Ctrl+Enter 永远执行另一种；
//   两个键都不对已排队的项做操作，输入框为空时都不发送任何东西)。
describe('core composer send intent', () => {
  it('sends nothing when the composer is empty, whatever the session is doing', () => {
    for (const status of ['idle', 'running', 'waiting', 'paused', 'completed']) {
      expect(coreComposerSendIntent({ status, text: '', sendMode: 'guide' })).toBe('none')
      expect(coreComposerSendIntent({ status, text: '   ', sendMode: 'queue', specialSend: true })).toBe('none')
    }
  })

  it('starts a new turn from an idle session with both keys', () => {
    expect(coreComposerSendIntent({ status: 'idle', text: '新任务', sendMode: 'guide' })).toBe('start')
    expect(coreComposerSendIntent({ status: 'idle', text: '新任务', sendMode: 'queue', specialSend: true })).toBe('start')
    expect(coreComposerSendIntent({ status: 'completed', text: '新任务' })).toBe('start')
  })

  it('guides by default while a turn runs, and Ctrl+Enter queues instead', () => {
    expect(coreComposerSendIntent({ status: 'running', text: '补充一句', sendMode: 'guide' })).toBe('guide')
    expect(coreComposerSendIntent({ status: 'running', text: '补充一句', sendMode: 'guide', specialSend: true })).toBe('queue')
    expect(coreComposerSendIntent({ status: 'waiting', text: '补充一句' })).toBe('guide')
    expect(coreComposerSendIntent({ status: 'running', text: '补充一句', specialSend: true })).toBe('queue')
  })

  it('queues while a turn runs in queue mode, and Ctrl+Enter guides directly past the queue', () => {
    expect(coreComposerSendIntent({ status: 'running', text: '先做这个', sendMode: 'queue' })).toBe('queue')
    expect(coreComposerSendIntent({ status: 'running', text: '先做这个', sendMode: 'queue', specialSend: true })).toBe('guide')
  })

  it('counts attachments as composer content', () => {
    expect(coreComposerSendIntent({ status: 'running', text: '', pendingAttachmentCount: 1, sendMode: 'queue' })).toBe('queue')
    expect(coreComposerSendIntent({ status: 'running', text: '', pendingAttachmentCount: 1, sendMode: 'queue', specialSend: true })).toBe('guide')
  })
})
