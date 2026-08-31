import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'src/demo/App.vue'), 'utf8')

describe('Core demo rollback host wiring', () => {
  it('wires rollback/fork through chat message turn boundaries, not the checkpoint graph', () => {
    expect(source).toMatch(/@rollback-message="handleRollbackMessage"/)
    expect(source).toMatch(/@fork-message="handleForkMessage"/)
    expect(source).toMatch(/session\.fork[\s\S]*turn_id: payload\.turnId/)
    expect(source).toMatch(/session\.rollback[\s\S]*turn_id: payload\.turnId/)
    expect(source).not.toMatch(/loadCheckpointGraph\(/)
  })

  it('reconnects the active thread after conversation and files are restored', () => {
    expect(source).toContain("const rollbackActiveTurn = computed(() => ['running', 'waiting'].includes(latestStatus.value))")
    expect(source).toMatch(/async function refreshAfterRollback\(\)[\s\S]*await refreshSessions\(\)[\s\S]*await selectSession\(sessionId\)/)
  })
})
