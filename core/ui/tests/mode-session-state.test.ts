import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createModeSessionState } from '../src/sessions/mode-state'
import { isInternalSession } from '../src/sessions/visibility'

describe('mode session isolation', () => {
  it('restores the original Agent session and separates mode drafts', async () => {
    const mode = ref('core:agent'), session = ref<string | null>('agent'), draft = ref('Agent draft')
    const select = vi.fn(async (id: string) => { session.value = id })
    const switchMode = createModeSessionState({ mode, session, draft, select, reset: vi.fn(), sessions: () => [{ id: 'agent', title: '', createdAt: '' }] })
    await switchMode('workflow:workflow')
    expect(session.value).toBeNull()
    expect(draft.value).toBe('')
    session.value = 'workflow:legacy'
    draft.value = 'Workflow draft'
    await switchMode('study:study')
    expect(session.value).toBeNull()
    session.value = 'study:main'
    await switchMode('core:agent')
    expect(session.value).toBe('agent')
    expect(draft.value).toBe('Agent draft')
    await switchMode('workflow:workflow')
    expect(draft.value).toBe('Workflow draft')
  })

  it('keeps the connection-scoped runtime alive while changing modes', async () => {
    const mode = ref('core:agent'), session = ref<string | null>('agent')
    const reset = vi.fn()
    const select = vi.fn(async (id: string) => { session.value = id })
    const switchMode = createModeSessionState({
      mode, session, draft: ref(''), reset, select,
      sessions: () => [{ id: 'agent', title: '', createdAt: '' }],
    })

    await switchMode('study:study')
    await switchMode('core:agent')

    expect(reset).toHaveBeenCalledTimes(2)
    expect(select).toHaveBeenCalledOnce()
    expect(select).toHaveBeenCalledWith('agent')
  })

  it('returns to an empty Agent start page and excludes legacy plugin threads', async () => {
    const mode = ref('core:agent'), session = ref<string | null>(null), select = vi.fn()
    const switchMode = createModeSessionState({ mode, session, draft: ref(''), select, reset: vi.fn(), sessions: () => [] })
    await switchMode('workflow:workflow')
    session.value = 'workflow:legacy'
    await switchMode('core:agent')
    expect(session.value).toBeNull()
    expect(select).not.toHaveBeenCalled()
    for (const id of ['workflow:legacy', 'study:main']) expect(isInternalSession({ id, title: '', createdAt: '' })).toBe(true)
  })
})
