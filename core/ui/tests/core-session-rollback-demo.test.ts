import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'src/demo/App.vue'), 'utf8')

describe('Core demo rollback host wiring', () => {
  it('mounts the shared rollback panel with the live operation client and active-turn guard', () => {
    expect(source).toContain('<CoreSessionRollback')
    expect(source).toContain(':request="requestConfigOperation"')
    expect(source).toContain(':active-turn="rollbackActiveTurn"')
    expect(source).toContain('@restored="refreshAfterRollback"')
    expect(source).toContain('@undone="refreshAfterRollback"')
  })

  it('reconnects the active thread after conversation and files are restored', () => {
    expect(source).toContain("const rollbackActiveTurn = computed(() => ['running', 'waiting'].includes(latestStatus.value))")
    expect(source).toMatch(/async function refreshAfterRollback\(\)[\s\S]*await refreshSessions\(\)[\s\S]*await selectSession\(sessionId\)/)
  })
})
