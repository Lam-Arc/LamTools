import assert from 'node:assert/strict'
import test from 'node:test'
import { removeSessionsByIds } from '../../src/lib/session-list.ts'

test('removeSessionsByIds removes only the deleted project sessions', () => {
  const sessions = [
    { id: 'keep-1', title: 'Keep one' },
    { id: 'drop-1', title: 'Drop one' },
    { id: 'keep-2', title: 'Keep two' },
  ]

  assert.deepEqual(removeSessionsByIds(sessions, new Set(['drop-1'])), [
    { id: 'keep-1', title: 'Keep one' },
    { id: 'keep-2', title: 'Keep two' },
  ])
})
