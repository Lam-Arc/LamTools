import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')

describe('Shared Core App rollback host wiring', () => {
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

  it('edits by clearing the conversation, never by requiring a checkpoint', () => {
    // Regression: the edit entry used to bail out with "该消息没有可编辑的节点"
    // whenever the turn had no checkpoint, so editing the first message failed.
    expect(source).not.toMatch(/getCheckpointForTurn/)
    expect(source).not.toMatch(/checkpointController\.restore/)
    const editHandler = source.slice(
      source.indexOf('async function handleEditMessage'),
      source.indexOf('async function handleEditMessage') + 1600,
    )
    expect(editHandler).toMatch(/session\.rollback[\s\S]*turn_id: payload\.turnId/)
    expect(editHandler).toMatch(/submitComposer\(\)/)
  })

  it('gates edit/fork/rollback on the compaction boundary, not on checkpoints', () => {
    expect(source).toMatch(/:locked-message-ids="lockedMessageIds"/)
    expect(source).toMatch(/lockedMessageIdsBeforeCompaction/)
    expect(source).not.toMatch(/:checkpoint-turn-ids=/)
  })

  it('confirms a rollback with a short prompt that states the file outcome', () => {
    expect(source).toMatch(/window\.confirm\('删除这条消息及之后的全部对话？有可用检查点时会一并恢复文件；没有则只清对话。'\)/)
  })
})
