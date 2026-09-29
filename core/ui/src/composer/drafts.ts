/**
 * Per-thread persistence for the unsent composer draft.
 *
 * The composer text is a single live value, so a shell switching sessions must
 * park the outgoing draft under its own thread and restore the incoming one.
 * Backing store is localStorage so an unsent draft also survives an app
 * restart or a reconnect (per thread, never merged across threads).
 */
export const CORE_COMPOSER_DRAFT_PREFIX = 'lamtools-core.composer.draft.'

/** Minimal storage surface (window.localStorage, or a test double). */
export interface ComposerDraftStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

export function composerDraftStorageKey(threadId: string): string {
  return `${CORE_COMPOSER_DRAFT_PREFIX}${threadId}`
}

/**
 * Resolve the default browser storage. Returns null in non-browser hosts and
 * when storage access is restricted (private mode, blocked cookies), where
 * drafts simply stay in-memory for the session.
 */
export function resolveComposerDraftStorage(): ComposerDraftStorage | null {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return null
    return window.localStorage
  } catch {
    return null
  }
}

export function readComposerDraft(
  storage: ComposerDraftStorage | null | undefined,
  threadId: string | null | undefined,
): string {
  if (!storage || !threadId) return ''
  try {
    return storage.getItem(composerDraftStorageKey(threadId)) ?? ''
  } catch {
    return ''
  }
}

/**
 * Persist, or drop when the text is empty, so a thread with no pending input
 * leaves no residue behind.
 */
export function writeComposerDraft(
  storage: ComposerDraftStorage | null | undefined,
  threadId: string | null | undefined,
  text: string,
): void {
  if (!storage || !threadId) return
  try {
    const key = composerDraftStorageKey(threadId)
    if (text) storage.setItem(key, text)
    else storage.removeItem(key)
  } catch {
    // A restricted storage context must never break composing.
  }
}

/** Drop a thread's draft, e.g. once the session itself is deleted. */
export function clearComposerDraft(
  storage: ComposerDraftStorage | null | undefined,
  threadId: string | null | undefined,
): void {
  if (!storage || !threadId) return
  try {
    storage.removeItem(composerDraftStorageKey(threadId))
  } catch {
    // Best-effort cleanup only.
  }
}
