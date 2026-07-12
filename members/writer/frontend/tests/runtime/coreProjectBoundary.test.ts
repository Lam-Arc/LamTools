import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeProjectAgents, requireProjectCreateResult } from '../../src/api/project-contract.ts'
import { createWriterProjectWorkspace, saveWriterProjectAgents } from '../../src/lib/project-workspace.ts'

test('Writer reads and saves the Core AGENTS.md payload without replacing editor content', async () => {
  const loaded = normalizeProjectAgents({ agents_md: { content: '# 中文规则\n\n保留编辑内容。', exists: true } })
  const saved: string[] = []

  assert.deepEqual(loaded, { content: '# 中文规则\n\n保留编辑内容。', exists: true })
  await saveWriterProjectAgents('project-1', '# 已编辑\n\n只保存 emit 内容。', async (_projectId, content) => {
    saved.push(content)
    return { content, exists: true }
  })

  assert.deepEqual(saved, ['# 已编辑\n\n只保存 emit 内容。'])
})

test('Writer creates one project session and selects the returned session', async () => {
  const calls: string[] = []
  const createdPayload = requireProjectCreateResult({
    project: { id: 'project-1', name: 'Docs', work_root: 'E:\\docs' },
    session: { id: 'session-1', title: 'Docs', work_root: 'E:\\docs' },
  })
  const created = await createWriterProjectWorkspace(
    { name: 'Docs', work_root: 'E:\\docs' },
    {
      createProject: async () => {
        calls.push('project.create')
        return createdPayload
      },
      onCreated: () => calls.push('created'),
      selectSession: async (sessionId) => calls.push(`select:${sessionId}`),
      refresh: async () => calls.push('refresh'),
    },
  )

  assert.equal(created.session.id, 'session-1')
  assert.deepEqual(calls, ['project.create', 'created', 'select:session-1', 'refresh'])
})
