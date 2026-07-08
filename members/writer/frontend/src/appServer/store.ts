import { defineStore } from 'pinia'
import { hydrateSnapshot } from './snapshot.ts'
import { appServerUrl, fetchAppServerToken, WriterAppServerClient } from './client.ts'
import type { WriterAppSnapshot, WriterCommandCatalogItem, WriterInputItem } from './protocol.ts'

const RECONNECT_BASE_MS = 25
const RECONNECT_MAX_MS = 2_000

export const useWriterAppServerStore = defineStore('writerAppServer', {
  state: () => ({
    state: null as WriterAppSnapshot | null,
    connectionState: 'closed' as 'connecting' | 'open' | 'closed' | 'error',
    client: null as WriterAppServerClient | null,
    lastError: '',
    activeApiBase: '',
    activeThreadId: '',
    reconnectAttempt: 0,
    reconnectTimer: null as ReturnType<typeof setTimeout> | null,
    connectionGeneration: 0,
  }),
  getters: {
    lastSeenSeq: (store) => store.state?.snapshot_seq ?? 0,
  },
  actions: {
    async connect(apiBase: string, threadId?: string) {
      this.clearReconnectTimer()
      this.activeApiBase = apiBase
      this.activeThreadId = threadId || ''
      this.reconnectAttempt = 0
      await this.openClient(apiBase, threadId)
    },
    async openClient(apiBase: string, threadId?: string) {
      const generation = ++this.connectionGeneration
      this.client?.close()
      const token = await fetchAppServerToken(apiBase)
      const client = new WriterAppServerClient({
        url: appServerUrl(apiBase, token),
        clientInfo: { name: 'lamwriter_frontend', title: 'LamWriter Frontend', version: '0.1.0' },
        onSnapshot: (snapshot) => this.hydrate(snapshot),
        onConnectionState: (state) => {
          if (this.connectionGeneration !== generation) return
          this.connectionState = state
          if (state === 'closed' || state === 'error') {
            this.scheduleReconnect()
          }
        },
      })
      this.client = client
      await client.connect({ threadId, lastSeenSeq: this.lastSeenSeq })
      if (threadId) {
        const response = await client.request('thread/resume', { thread_id: threadId, last_seen_seq: this.lastSeenSeq })
        if (this.connectionGeneration !== generation) return
        this.applyResponse(response)
      }
      this.reconnectAttempt = 0
    },
    disconnect() {
      this.clearReconnectTimer()
      this.activeApiBase = ''
      this.activeThreadId = ''
      this.connectionGeneration += 1
      this.client?.close()
      this.client = null
      this.state = null
      this.connectionState = 'closed'
    },
    clearReconnectTimer() {
      if (!this.reconnectTimer) return
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    },
    scheduleReconnect() {
      if (!this.activeApiBase || !this.activeThreadId || this.reconnectTimer) return
      const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** this.reconnectAttempt)
      this.reconnectAttempt += 1
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null
        void this.reconnectActiveThread()
      }, delay)
    },
    async reconnectActiveThread() {
      if (!this.activeApiBase || !this.activeThreadId) return
      try {
        await this.openClient(this.activeApiBase, this.activeThreadId)
      } catch (error) {
        this.lastError = error instanceof Error ? error.message : String(error)
        this.connectionState = 'error'
        this.scheduleReconnect()
      }
    },
    hydrate(snapshot: WriterAppSnapshot) {
      this.state = hydrateSnapshot(snapshot)
    },
    applyResponse(response: Record<string, unknown>) {
      const snapshot = response.snapshot
      if (isWriterAppSnapshot(snapshot)) {
        this.hydrate(snapshot)
      }
    },
    async startThread(threadId: string) {
      await this.ensureClient()
      const response = await this.client!.request('thread/start', { thread_id: threadId })
      this.applyResponse(response)
    },
    async startTurn(
      threadId: string,
      input: string | WriterInputItem[],
      workRoot?: string,
      options: { thinking_enabled?: boolean; thinking_budget?: number; shallow_thinking_enabled?: boolean } = {},
    ) {
      await this.ensureClient()
      const inputItems = typeof input === 'string' ? [{ type: 'text' as const, text: input }] : input
      const response = await this.client!.request('turn/start', {
        thread_id: threadId,
        client_message_id: crypto.randomUUID(),
        input: inputItems,
        work_root: workRoot,
        ...options,
      })
      this.applyResponse(response)
    },
    async queueInput(threadId: string, input: string | WriterInputItem[]) {
      await this.ensureClient()
      const inputItems = typeof input === 'string' ? [{ type: 'text' as const, text: input }] : input
      const response = await this.client!.request('queue/create', {
        thread_id: threadId,
        client_message_id: crypto.randomUUID(),
        input: inputItems,
      })
      this.applyResponse(response)
    },
    async updateQueueInput(threadId: string, queueItemId: string, text: string) {
      await this.ensureClient()
      const response = await this.client!.request('queue/update', {
        thread_id: threadId,
        queue_item_id: queueItemId,
        text,
      })
      this.applyResponse(response)
    },
    async deleteQueueInput(threadId: string, queueItemId: string) {
      await this.ensureClient()
      const response = await this.client!.request('queue/delete', {
        thread_id: threadId,
        queue_item_id: queueItemId,
      })
      this.applyResponse(response)
    },
    async listCommands(workRoot?: string): Promise<WriterCommandCatalogItem[]> {
      await this.ensureClient()
      const response = await this.client!.request('command.catalog', {
        ...(workRoot ? { work_root: workRoot } : {}),
      })
      return Array.isArray(response.commands) ? response.commands as WriterCommandCatalogItem[] : []
    },
    async executeCommand(threadId: string, command: string, workRoot?: string): Promise<Record<string, unknown>> {
      await this.ensureClient()
      const response = await this.client!.request('command.execute', {
        thread_id: threadId,
        command,
        ...(workRoot ? { work_root: workRoot } : {}),
      })
      this.applyResponse(response)
      return response.result && typeof response.result === 'object'
        ? response.result as Record<string, unknown>
        : {}
    },
    async steerTurn(threadId: string, turnId: string, text: string) {
      await this.ensureClient()
      const response = await this.client!.request('turn/steer', {
        thread_id: threadId,
        turn_id: turnId,
        client_message_id: crypto.randomUUID(),
        input: [{ type: 'text', text }],
      })
      this.applyResponse(response)
    },
    async interruptTurn(threadId: string) {
      await this.ensureClient()
      const response = await this.client!.request('turn/interrupt', {
        thread_id: threadId,
      })
      this.applyResponse(response)
    },
    async respondApproval(requestId: string, decision: string, guidance?: string) {
      await this.ensureClient()
      const sentResponse = this.client!.respondServerRequest(requestId, {
        decision,
        guidance,
      })
      if (sentResponse) return
      const response = await this.client!.request('approval/respond', {
        request_id: requestId,
        decision,
        guidance,
      })
      this.applyResponse(response)
    },
    async ensureClient() {
      if (!this.client) {
        throw new Error('Writer App Server client is not connected')
      }
    },
  },
})

function isWriterAppSnapshot(value: unknown): value is WriterAppSnapshot {
  return Boolean(value)
    && typeof value === 'object'
    && typeof (value as { thread_id?: unknown }).thread_id === 'string'
    && typeof (value as { snapshot_seq?: unknown }).snapshot_seq === 'number'
}
