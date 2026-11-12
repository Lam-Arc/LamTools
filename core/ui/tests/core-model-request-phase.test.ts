import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import {
  applyCoreAppEvent,
  createCoreWorkbenchProjectionCache,
  hydrateSnapshot,
  selectCoreWorkbenchMessages,
  selectCoreWorkbenchMessagesWindow,
  type CoreAppEvent,
  type CoreAppSnapshot,
} from '../src/appServer'
import ChatThread from '../src/components/ChatThread.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

const testTransport = createFakeTransport()

function runningSnapshot(): CoreAppSnapshot {
  const turn = { turn_id: 'turn-phase', status: 'running', items: ['user-1'] }
  return hydrateSnapshot({
    thread_id: 'thread-phase',
    snapshot_seq: 1,
    status: 'running',
    turns: { 'turn-phase': turn },
    items: {
      'user-1': {
        item_id: 'user-1',
        turn_id: 'turn-phase',
        type: 'userMessage',
        content: [{ type: 'text', text: '你好' }],
      },
    },
    item_order: ['user-1'],
    core: {
      thread_id: 'thread-phase',
      snapshot_seq: 1,
      status: 'running',
      item_order: ['user-1'],
      turns: { 'turn-phase': turn },
      items: {
        'user-1': {
          item_id: 'user-1',
          turn_id: 'turn-phase',
          kind: 'message',
          status: 'completed',
          payload: { type: 'userMessage', content: [{ type: 'text', text: '你好' }] },
        },
      },
    },
  } as CoreAppSnapshot)
}

function phaseEvent(phase: string, eventId = `phase-${phase}`): CoreAppEvent {
  return {
    event_id: eventId,
    seq: 2,
    thread_id: 'thread-phase',
    turn_id: 'turn-phase',
    method: 'core/runItem',
    created_at: '2026-11-11T00:00:00Z',
    payload: {
      event_id: eventId,
      thread_id: 'thread-phase',
      turn_id: 'turn-phase',
      kind: 'model_phase',
      status: 'running',
      payload: { phase, response_index: 0, elapsed_ms: 40, at_ms: 1_760_000_000_000 },
    },
  } as CoreAppEvent
}

function waitingMessage(metadata: Record<string, unknown>): CoreMessage {
  return {
    id: 'assistant:waiting:user-1',
    role: 'assistant',
    content: '',
    timestamp: '2026-11-11T00:00:00Z',
    metadata: { live: true, initialWaiting: true, ...metadata },
    parts: [],
  }
}

describe('model request phase', () => {
  it('records the phase on the existing turn without creating a transcript item', () => {
    const next = applyCoreAppEvent(runningSnapshot(), phaseEvent('request_sent'))

    expect(next.core?.turns?.['turn-phase']?.model_phase).toBe('request_sent')
    expect(next.core?.turns?.['turn-phase']?.model_phase_elapsed_ms).toBe(40)
    expect(next.core?.items?.['phase-request_sent']).toBeUndefined()
    expect(next.core?.item_order).toEqual(['user-1'])
  })

  it('attaches the latest phase to the waiting assistant message', () => {
    const sent = applyCoreAppEvent(runningSnapshot(), phaseEvent('request_sent'))
    const waiting = selectCoreWorkbenchMessages(sent, { active: true })
      .find(message => message.metadata?.initialWaiting === true)

    expect(waiting?.metadata?.modelPhase).toBe('request_sent')
  })

  it('does not keep a cached waiting message when only the phase changes', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const building = selectCoreWorkbenchMessagesWindow(
      runningSnapshot(),
      { active: true },
      cache,
    ).messages
    const sentSnapshot = applyCoreAppEvent(runningSnapshot(), phaseEvent('request_sent'))
    const sent = selectCoreWorkbenchMessagesWindow(sentSnapshot, { active: true }, cache).messages

    const before = building.find(message => message.metadata?.initialWaiting === true)
    const after = sent.find(message => message.metadata?.initialWaiting === true)
    expect(before?.metadata?.modelPhase).toBeUndefined()
    expect(after?.metadata?.modelPhase).toBe('request_sent')
  })

  it('switches the waiting indicator between the two animations', () => {
    const sending = mount(ChatThread, {
      props: { messages: [waitingMessage({ modelPhase: 'request_building' })], transport: testTransport },
    })
    expect(sending.find('.request-phase').attributes('data-phase')).toBe('sending')

    const waiting = mount(ChatThread, {
      props: { messages: [waitingMessage({ modelPhase: 'request_sent' })], transport: testTransport },
    })
    expect(waiting.find('.request-phase').attributes('data-phase')).toBe('waiting')
  })

  it('keeps the shallow-thinking label and drives its dots by the same phase', () => {
    const wrapper = mount(ChatThread, {
      props: {
        messages: [waitingMessage({ modelPhase: 'request_sent', shallowThinkingPending: true })],
        transport: testTransport,
      },
    })

    expect(wrapper.find('.initial-waiting-indicator').text()).toContain('shallow thinking...')
    expect(wrapper.find('.shallow-thinking-pending').attributes('data-phase')).toBe('waiting')
    expect(wrapper.find('.request-phase').exists()).toBe(false)
  })
})
