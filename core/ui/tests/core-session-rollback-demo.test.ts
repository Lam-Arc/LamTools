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

  it('reconnects the active thread after the conversation is restored', () => {
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

  it('confirms a rollback in the app dialog, and says files are untouched', () => {
    // 原生 confirm 会顶着 "127.0.0.1:5173 显示" 这样的地址标题，观感与应用无关；
    // 撤回确认走应用内确认框。
    const handler = source.slice(
      source.indexOf('function handleRollbackMessage'),
      source.indexOf('async function confirmRollbackMessage'),
    )
    expect(handler).not.toMatch(/window\.confirm/)
    expect(handler).toMatch(/askConfirm\(\{ title: '撤回'/)
    expect(source).toMatch(/<CoreConfirmDialog[\s\S]*?:open="Boolean\(appConfirm\)"/)
    expect(source).toMatch(/@cancel="appConfirm = null"/)
    expect(source).toMatch(/@confirm="confirmAppAction"/)

    const confirmed = source.slice(
      source.indexOf('async function rollbackTurn'),
      source.indexOf('async function handleEditMessage'),
    )
    expect(confirmed).toMatch(/session\.rollback[\s\S]*turn_id: turnId/)
    expect(confirmed).toMatch(/showToast\('notice', '已删除此轮及之后的对话；文件与成果保持不变。'\)/)
  })
})
