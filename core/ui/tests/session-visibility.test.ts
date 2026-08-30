import { describe, expect, it } from 'vitest'

import { isInternalSession } from '../src/sessions/visibility'

describe('Core session visibility', () => {
  it('keeps Workflow implementation threads out of the ordinary session list', () => {
    expect(isInternalSession({ id: 'workflow_thread_abcd', title: 'workflow_thread_abcd', createdAt: '' })).toBe(true)
  })

  it('keeps plugin-owned sessions out of the ordinary session list', () => {
    expect(isInternalSession({ id: 'plugin-thread', title: 'plugin-thread', createdAt: '', metadata: { owner_plugin: 'workflow' } })).toBe(true)
  })

  it('leaves a regular user session visible', () => {
    expect(isInternalSession({ id: 'thread-1', title: 'Work', createdAt: '' })).toBe(false)
  })
})
