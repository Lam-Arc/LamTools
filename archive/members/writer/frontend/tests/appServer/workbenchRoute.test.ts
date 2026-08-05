import assert from 'node:assert/strict'
import test from 'node:test'
import { workbenchSessionRouteQuery } from '../../src/utils/workbenchRoute.ts'

test('workbench session route query preserves other query params while selecting a session', () => {
  const query = workbenchSessionRouteQuery({ view: 'thread', session: 'old' }, 'new-session')

  assert.deepEqual(query, { view: 'thread', session: 'new-session' })
})

test('workbench session route query removes session when no session is active', () => {
  const query = workbenchSessionRouteQuery({ view: 'thread', session: 'old' }, null)

  assert.deepEqual(query, { view: 'thread' })
})
