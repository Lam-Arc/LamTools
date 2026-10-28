import { effectScope, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createWorkbench } from '../src/workbench/createWorkbench'
import { createFakeTransport } from './fake-transport'
import { usePendingAttachments } from '../src/composables/usePendingAttachments'
import type { CoreAppEvent, CoreAppSnapshot } from '../src/appServer/protocol'

// user:“做吧”+(用真实工作台验证回执、跨聊天草稿和附件持久化之间的接线)。
afterEach(() => { localStorage.clear() })
function snapshot(thread: string): CoreAppSnapshot {
  return { thread_id: thread, snapshot_seq: 0, status: 'idle', turns: {}, items: {}, item_order: [], queue: [], requests: {} }
}

function setup() {
  const scope = effectScope()
  const stored = new Map<string, string>()
  let receiveEvent!: (event: CoreAppEvent) => void
  let reply!: (value: Record<string, unknown>) => void
  const startReply = new Promise<Record<string, unknown>>(resolve => { reply = resolve })
  let sentParams: Record<string, unknown> = {}
  const workbench = scope.run(() => createWorkbench({
    transport: createFakeTransport(),
    composerDraftStorage: {
      getItem: key => stored.get(key) || null,
      setItem: (key, value) => { stored.set(key, value) },
      removeItem: key => { stored.delete(key) },
    },
    sessions: { listSessions: async () => [] },
    clientFactory: { createClient: callbacks => {
      receiveEvent = callbacks.onEvent
      return {
        connect: async () => { callbacks.onConnectionState('open') },
        close: () => {}, respondServerRequest: () => false,
        request: async (method, params) => {
          if (method === 'turn/start') { sentParams = params || {}; return startReply }
          return { snapshot: snapshot(String(params?.thread_id || 'a')) }
        },
      }
    } },
  }))!
  return { scope, workbench, stored, reply, receive: (event: CoreAppEvent) => receiveEvent(event), params: () => sentParams }
}

function receipt(id: string, method: string, seq: number): CoreAppEvent {
  return { event_id: `event-${seq}`, seq, thread_id: 'a', turn_id: 'turn-a', client_message_id: id,
    method, created_at: new Date().toISOString(), payload: method === 'item/started'
      ? { type: 'userMessage', content: [{ type: 'text', text: 'original' }] }
      : { input: [{ type: 'text', text: 'original' }] },
    ...(method === 'item/started' ? { item_id: 'user-a' } : {}),
  }
}

describe('submission workbench integration', () => {
  it('replaces only its own pending row when the response materializes the real user message', async () => {
    const s = setup()
    try {
      await s.workbench.selectSession('a')
      s.workbench.composerText.value = 'original'
      const sending = s.workbench.composer.submit({ clearComposer: true })
      await vi.waitFor(() => expect(s.params().client_message_id).toBeTypeOf('string'))
      const id = String(s.params().client_message_id)
      expect(s.workbench.composer.submissions.value).toHaveLength(1)
      s.reply({ events: [receipt(id, 'turn/accepted', 1), receipt(id, 'item/started', 2)] })
      await sending; await nextTick()
      expect(s.workbench.composerText.value).toBe('')
      expect(s.workbench.composer.submissions.value).toEqual([])
      expect(s.workbench.snapshot.value?.items?.['user-a']?.content).toEqual([{ type: 'text', text: 'original' }])
    } finally { s.scope.stop() }
  })

  it('keeps B draft and attachments while a late A reply retires only the parked A draft', async () => {
    const s = setup()
    try {
      await s.workbench.selectSession('a')
      s.workbench.composerText.value = 'original'
      s.workbench.attachments.value = [{ type: 'attachment', attachment_id: 'file-a' }]
      const sending = s.workbench.composer.submit({ clearComposer: true })
      await vi.waitFor(() => expect(s.params().client_message_id).toBeTypeOf('string'))
      await s.workbench.selectSession('b')
      s.workbench.composerText.value = 'draft B'
      s.workbench.attachments.value = [{ type: 'attachment', attachment_id: 'file-b' }]
      await nextTick()
      s.reply({ events: [receipt(String(s.params().client_message_id), 'turn/accepted', 1)] })
      await sending; await nextTick()
      expect(s.workbench.activeSessionId.value).toBe('b')
      expect(s.workbench.activeThreadId.value).toBe('b')
      expect(s.workbench.composerText.value).toBe('draft B')
      expect(s.workbench.attachments.value).toEqual([{ type: 'attachment', attachment_id: 'file-b' }])
      expect([...s.stored.entries()].find(([key]) => key.endsWith('a'))).toBeUndefined()
      expect(s.workbench.composer.submissions.value.every(record => record.threadId === 'a')).toBe(true)
    } finally { s.scope.stop() }
  })

  it('removes accepted files from the parked tray without touching the current chat', async () => {
    const scope = effectScope()
    const tray = scope.run(() => usePendingAttachments())!
    try {
      tray.setSession('a')
      tray.addUploaded({ id: 'file-a', filename: 'a.txt', mime_type: 'text/plain', size: 1, preview_type: 'external' })
      await nextTick()
      tray.setSession('b')
      tray.addUploaded({ id: 'file-b', filename: 'b.txt', mime_type: 'text/plain', size: 1, preview_type: 'external' })
      tray.removeSubmittedAttachments('a', [{ type: 'attachment', attachment_id: 'file-a' }])
      expect(tray.pendingAttachments.value.map(file => file.id)).toEqual(['file-b'])
      tray.setSession('a')
      expect(tray.pendingAttachments.value).toEqual([])
    } finally { scope.stop() }
  })
})
