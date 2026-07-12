import { defineStore } from 'pinia'
import {
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  type CoreAppServerRuntimeClient,
} from '@lamtools/ui'
import { hydrateSnapshot } from './snapshot.ts'
import { appServerUrl, fetchAppServerToken, WriterAppServerClient } from './client.ts'
import type { WriterAppSnapshot, WriterCommandCatalogItem, WriterInputItem } from './protocol.ts'

function createWriterRuntimeController(runtime: ReturnType<typeof createCoreAppServerRuntimeState<WriterAppSnapshot, CoreAppServerRuntimeClient>>) {
  return createCoreAppServerRuntimeController<WriterAppSnapshot, WriterInputItem, WriterCommandCatalogItem, CoreAppServerRuntimeClient>(
    runtime,
    {
      hydrateSnapshot,
      async createClient({ apiBase, onSnapshot, onConnectionState }) {
        const token = await fetchAppServerToken(apiBase)
        return new WriterAppServerClient({
          url: appServerUrl(apiBase, token),
          clientInfo: { name: 'lamwriter_frontend', title: 'LamWriter Frontend', version: '0.1.0' },
          onSnapshot,
          onConnectionState,
        })
      },
    },
  )
}

export const useWriterAppServerStore = defineStore('writerAppServer', {
  state: () => ({
    runtime: createCoreAppServerRuntimeState<WriterAppSnapshot, CoreAppServerRuntimeClient>(),
  }),
  getters: {
    state: (store) => store.runtime.state,
    connectionState: (store) => store.runtime.connectionState,
    client: (store) => store.runtime.client,
    lastError: (store) => store.runtime.lastError,
    activeApiBase: (store) => store.runtime.activeApiBase,
    activeThreadId: (store) => store.runtime.activeThreadId,
    reconnectAttempt: (store) => store.runtime.reconnectAttempt,
    reconnectTimer: (store) => store.runtime.reconnectTimer,
    connectionGeneration: (store) => store.runtime.connectionGeneration,
    lastSeenSeq: (store) => store.runtime.state?.snapshot_seq ?? 0,
  },
  actions: {
    async connect(apiBase: string, threadId?: string) {
      await createWriterRuntimeController(this.runtime).connect(apiBase, threadId)
    },
    async openClient(apiBase: string, threadId?: string) {
      await createWriterRuntimeController(this.runtime).openClient(apiBase, threadId)
    },
    disconnect() {
      createWriterRuntimeController(this.runtime).disconnect()
    },
    clearReconnectTimer() {
      createWriterRuntimeController(this.runtime).clearReconnectTimer()
    },
    scheduleReconnect() {
      createWriterRuntimeController(this.runtime).scheduleReconnect()
    },
    async reconnectActiveThread() {
      await createWriterRuntimeController(this.runtime).reconnectActiveThread()
    },
    hydrate(snapshot: WriterAppSnapshot) {
      createWriterRuntimeController(this.runtime).hydrate(snapshot)
    },
    applyResponse(response: Record<string, unknown>) {
      createWriterRuntimeController(this.runtime).applyResponse(response)
    },
    async startThread(threadId: string) {
      await createWriterRuntimeController(this.runtime).startThread(threadId)
    },
    async startTurn(
      threadId: string,
      input: string | WriterInputItem[],
      workRoot?: string,
      options: { thinking_enabled?: boolean; thinking_budget?: number; shallow_thinking_enabled?: boolean } = {},
    ) {
      await createWriterRuntimeController(this.runtime).startTurn(threadId, input, workRoot, options)
    },
    async queueInput(threadId: string, input: string | WriterInputItem[]) {
      await createWriterRuntimeController(this.runtime).queueInput(threadId, input)
    },
    async updateQueueInput(threadId: string, queueItemId: string, text: string) {
      await createWriterRuntimeController(this.runtime).updateQueueInput(threadId, queueItemId, text)
    },
    async deleteQueueInput(threadId: string, queueItemId: string) {
      await createWriterRuntimeController(this.runtime).deleteQueueInput(threadId, queueItemId)
    },
    async guideQueueInput(threadId: string, turnId: string, queueItemId: string, text?: string) {
      return await createWriterRuntimeController(this.runtime).guideQueueInput(threadId, turnId, queueItemId, text)
    },
    async listCommands(workRoot?: string): Promise<WriterCommandCatalogItem[]> {
      return await createWriterRuntimeController(this.runtime).listCommands(workRoot)
    },
    async executeCommand(threadId: string, command: string, workRoot?: string): Promise<Record<string, unknown>> {
      return await createWriterRuntimeController(this.runtime).executeCommand(threadId, command, workRoot)
    },
    async steerTurn(threadId: string, turnId: string, text: string) {
      await createWriterRuntimeController(this.runtime).steerTurn(threadId, turnId, text)
    },
    async interruptTurn(threadId: string) {
      await createWriterRuntimeController(this.runtime).interruptTurn(threadId)
    },
    async respondApproval(requestId: string, decision: string, guidance?: string) {
      await createWriterRuntimeController(this.runtime).respondApproval(requestId, decision, guidance)
    },
  },
})
