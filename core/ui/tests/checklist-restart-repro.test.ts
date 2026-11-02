import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { hydrateSnapshot, selectCoreWorkbenchMessages } from '../src/appServer'
import { resolveChecklistGroups } from '../src/runtime/checklist'

// 真实快照回归：后端 snapshot_store.load() 重建的快照（重启后 UI 连上时收到的
// 就是它）走一次前端投影 + checklist 解析，卡不得为空。
// 快照文件用 scripts 侧导出脚本生成（见 scripts/export-checklist-snapshot.py）。
const SNAPSHOT_PATH = process.env.CHK_SNAPSHOT_PATH || ''

describe.skipIf(!SNAPSHOT_PATH)('checklist restore (real snapshot)', () => {
  it('rebuilds checklist groups from the restored snapshot', () => {
    const raw = JSON.parse(readFileSync(SNAPSHOT_PATH, 'utf-8'))
    const snapshot = hydrateSnapshot(raw)
    const messages = selectCoreWorkbenchMessages(snapshot, { source: 'core_app_server' })
    const lastUserIndex = messages.findLastIndex(m => m.role === 'user')
    console.log('messages:', messages.length, 'lastUserIndex:', lastUserIndex,
      'lastUserContent:', JSON.stringify(messages[lastUserIndex]?.content || '').slice(0, 80))
    const groups = resolveChecklistGroups(messages, snapshot.core?.task_plan)
    console.log('checklist groups:', groups.length)
    for (const g of groups) {
      console.log(' group', g.id, g.status, 'steps:', g.steps.length)
    }
    expect(groups.length).toBeGreaterThan(0)
    expect(groups[0]?.steps.length).toBeGreaterThan(0)
  })
})
