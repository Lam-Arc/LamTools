import { effectScope, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import {
  CORE_COMPOSER_DRAFT_PREFIX,
  clearComposerDraft,
  composerDraftStorageKey,
  readComposerDraft,
  writeComposerDraft,
  type ComposerDraftStorage,
} from '../src/composer/drafts'
import { createWorkbench } from '../src/workbench/createWorkbench'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '../src/transport'

/** Minimal transport: these tests never drive RPC, only the composer draft. */
class FakeTransport implements LamToolsTransport {
  private state: TransportConnectionState = 'disconnected'
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  async connect(): Promise<void> { this.state = 'connected' }
  async close(): Promise<void> {
    this.state = 'disconnected'
    for (const listener of this.stateListeners) listener(this.state)
  }
  async request<TResponse = unknown>(_request: TransportRequest): Promise<TResponse> {
    return {} as TResponse
  }
  send(_message: TransportMessage): void {}
  subscribe(_handler: (message: TransportMessage) => void): () => void { return () => {} }
  onState(handler: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(handler)
    handler(this.state)
    return () => this.stateListeners.delete(handler)
  }
  getState() { return this.state }
}

function memoryStorage(): ComposerDraftStorage & { readonly map: Map<string, string> } {
  const map = new Map<string, string>()
  return {
    map,
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => { map.set(key, value) },
    removeItem: (key) => { map.delete(key) },
  }
}

/** Watchers flush on `nextTick`; two passes settle the switch-then-restore chain. */
async function flush(): Promise<void> {
  await nextTick()
  await nextTick()
}

describe('composer draft storage', () => {
  it('namespaces by thread and drops the key when the draft is empty', () => {
    const storage = memoryStorage()
    writeComposerDraft(storage, 'thread-a', 'hello a')
    writeComposerDraft(storage, 'thread-b', 'hello b')
    expect(composerDraftStorageKey('thread-a')).toBe(`${CORE_COMPOSER_DRAFT_PREFIX}thread-a`)
    expect(readComposerDraft(storage, 'thread-a')).toBe('hello a')
    expect(readComposerDraft(storage, 'thread-b')).toBe('hello b')
    // Emptying one thread never touches its neighbour.
    writeComposerDraft(storage, 'thread-a', '')
    expect(storage.map.has(composerDraftStorageKey('thread-a'))).toBe(false)
    expect(readComposerDraft(storage, 'thread-b')).toBe('hello b')
  })

  it('persists across a fresh read (restart path) and clears explicitly', () => {
    const storage = memoryStorage()
    writeComposerDraft(storage, 'thread-a', 'unsent')
    // A later session re-reads the same key: persistence, not in-memory state.
    expect(readComposerDraft(storage, 'thread-a')).toBe('unsent')
    clearComposerDraft(storage, 'thread-a')
    expect(readComposerDraft(storage, 'thread-a')).toBe('')
  })

  it('is inert and non-throwing without storage, thread, or a working store', () => {
    expect(readComposerDraft(null, 'thread-a')).toBe('')
    expect(readComposerDraft(memoryStorage(), null)).toBe('')
    expect(() => writeComposerDraft(null, 'thread-a', 'x')).not.toThrow()
    expect(() => writeComposerDraft(memoryStorage(), '', 'x')).not.toThrow()
    const hostile: ComposerDraftStorage = {
      getItem: () => { throw new Error('blocked') },
      setItem: () => { throw new Error('blocked') },
      removeItem: () => { throw new Error('blocked') },
    }
    expect(readComposerDraft(hostile, 'thread-a')).toBe('')
    expect(() => writeComposerDraft(hostile, 'thread-a', 'x')).not.toThrow()
    expect(() => clearComposerDraft(hostile, 'thread-a')).not.toThrow()
  })
})

describe('workbench composer draft isolation', () => {
  it('keeps one unsent draft per session, restores on switch-back, and survives a restart', async () => {
    window.localStorage.clear()
    const open = () => {
      const scope = effectScope()
      const runtime = scope.run(() => createWorkbench({ transport: new FakeTransport() }))!
      return { scope, runtime }
    }

    const first = open()
    first.runtime.activeSessionId.value = 'thread-a'
    await flush()
    first.runtime.composerText.value = '草稿 A'
    await flush()
    expect(window.localStorage.getItem(composerDraftStorageKey('thread-a'))).toBe('草稿 A')

    // Switching away shows the target session's own (empty) draft — no leak.
    first.runtime.activeSessionId.value = 'thread-b'
    await flush()
    expect(first.runtime.composerText.value).toBe('')

    first.runtime.composerText.value = 'draft B'
    await flush()
    // Back to A: the exact unsent text is restored, B keeps its own.
    first.runtime.activeSessionId.value = 'thread-a'
    await flush()
    expect(first.runtime.composerText.value).toBe('草稿 A')
    expect(window.localStorage.getItem(composerDraftStorageKey('thread-b'))).toBe('draft B')
    first.scope.stop()

    // Restart: a brand-new workbench over the same storage restores per thread.
    const second = open()
    second.runtime.activeSessionId.value = 'thread-b'
    await flush()
    expect(second.runtime.composerText.value).toBe('draft B')
    second.runtime.activeSessionId.value = 'thread-a'
    await flush()
    expect(second.runtime.composerText.value).toBe('草稿 A')
    second.scope.stop()
  })

  it('clearing on submit drops only the submitted session draft', async () => {
    window.localStorage.clear()
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({ transport: new FakeTransport() }))!
    runtime.activeSessionId.value = 'thread-a'
    await flush()
    runtime.composerText.value = 'send me'
    await flush()
    runtime.composerText.value = ''
    await flush()
    expect(window.localStorage.getItem(composerDraftStorageKey('thread-a'))).toBeNull()
    scope.stop()
  })

  it('uses an injected storage instead of window.localStorage', async () => {
    window.localStorage.clear()
    const storage = memoryStorage()
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      composerDraftStorage: storage,
    }))!
    runtime.activeSessionId.value = 'thread-x'
    await flush()
    runtime.composerText.value = 'x draft'
    await flush()
    expect(storage.map.get(composerDraftStorageKey('thread-x'))).toBe('x draft')
    expect(window.localStorage.getItem(composerDraftStorageKey('thread-x'))).toBeNull()

    // An injected null disables persistence entirely; composing still works.
    const noStoreScope = effectScope()
    const noStore = noStoreScope.run(() => createWorkbench({
      transport: new FakeTransport(),
      composerDraftStorage: null,
    }))!
    noStore.activeSessionId.value = 'thread-y'
    await flush()
    noStore.composerText.value = 'y draft'
    await flush()
    expect(noStore.composerText.value).toBe('y draft')
    expect(window.localStorage.getItem(composerDraftStorageKey('thread-y'))).toBeNull()
    scope.stop()
    noStoreScope.stop()
  })
})
