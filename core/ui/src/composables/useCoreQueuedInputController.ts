import { computed, nextTick, ref, type Ref } from 'vue'

export interface CoreQueuedInputControllerItem {
  id: string
  thread_id: string
  text: string
  status?: string
}

export interface UseCoreQueuedInputControllerOptions {
  activeTurnId: Readonly<Ref<string>>
  ensureConnected(threadId: string): Promise<void>
  updateQueueInput(threadId: string, queueItemId: string, text: string): Promise<void>
  deleteQueueInput(threadId: string, queueItemId: string): Promise<void>
  guideQueueInput(
    threadId: string,
    turnId: string,
    queueItemId: string,
    text?: string,
  ): Promise<{ applied: boolean; reason: string }>
  onError?(error: unknown): void
}

export function useCoreQueuedInputController(options: UseCoreQueuedInputControllerOptions) {
  const editingId = ref<string | null>(null)
  const draft = ref('')
  const lastError = ref('')
  const submittingItemIds = ref(new Set<string>())
  const canGuide = computed(() => Boolean(options.activeTurnId.value))

  async function beginEdit(item: CoreQueuedInputControllerItem): Promise<boolean> {
    if (item.status !== 'queued' || submittingItemIds.value.has(item.id)) return false
    editingId.value = item.id
    draft.value = item.text
    await nextTick()
    const input = Array.from(document.querySelectorAll<HTMLInputElement>('[data-queued-input-edit]'))
      .find(element => element.dataset.queuedInputEdit === item.id)
    input?.focus()
    return true
  }

  function cancelEdit() {
    editingId.value = null
    draft.value = ''
  }

  async function save(item: CoreQueuedInputControllerItem): Promise<boolean> {
    if (editingId.value !== item.id || submittingItemIds.value.has(item.id)) return false
    const text = draft.value.trim()
    if (!text) {
      cancelEdit()
      return false
    }
    // Claim the item for the whole save: Enter + blur can otherwise fire two
    // concurrent updates (audit 19 S3 — guide() already uses this pattern).
    submittingItemIds.value = new Set([...submittingItemIds.value, item.id])
    try {
      await options.ensureConnected(item.thread_id)
      if (text !== item.text) {
        await options.updateQueueInput(item.thread_id, item.id, text)
      }
      return true
    } catch (error) {
      reportError(error)
      return false
    } finally {
      const next = new Set(submittingItemIds.value)
      next.delete(item.id)
      submittingItemIds.value = next
      cancelEdit()
    }
  }

  async function remove(item: CoreQueuedInputControllerItem): Promise<boolean> {
    if (submittingItemIds.value.has(item.id)) return false
    try {
      await options.ensureConnected(item.thread_id)
      if (editingId.value === item.id) cancelEdit()
      await options.deleteQueueInput(item.thread_id, item.id)
      return true
    } catch (error) {
      reportError(error)
      return false
    }
  }

  async function guide(item: CoreQueuedInputControllerItem): Promise<boolean> {
    if (item.status !== 'queued' || !canGuide.value || submittingItemIds.value.has(item.id)) return false
    submittingItemIds.value = new Set([...submittingItemIds.value, item.id])
    const turnId = options.activeTurnId.value
    let text = item.text
    if (editingId.value === item.id) {
      text = draft.value.trim() || item.text
    }
    try {
      await options.ensureConnected(item.thread_id)
      const result = await options.guideQueueInput(item.thread_id, turnId, item.id, text)
      if (!result.applied) {
        lastError.value = result.reason || 'Queue guidance was not applied'
        return false
      }
      cancelEdit()
      lastError.value = ''
      return true
    } catch (error) {
      reportError(error)
      return false
    } finally {
      const next = new Set(submittingItemIds.value)
      next.delete(item.id)
      submittingItemIds.value = next
    }
  }

  function reportError(error: unknown) {
    lastError.value = error instanceof Error ? error.message : String(error)
    options.onError?.(error)
  }

  return {
    beginEdit,
    canGuide,
    cancelEdit,
    draft,
    editingId,
    guide,
    lastError,
    remove,
    save,
    submittingItemIds,
  }
}
