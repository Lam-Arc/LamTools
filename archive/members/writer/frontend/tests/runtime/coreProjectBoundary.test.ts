import assert from 'node:assert/strict'
import test from 'node:test'

import { buildCoreProjectGroups } from '@lamtools/ui'
import { normalizeProjectAgents, requireProjectCreateResult } from '../../src/api/project-contract.ts'
import {
  createWriterProjectAgentsSaveHandler,
  shouldApplyWriterProjectAgents,
} from '../../src/lib/project-agents-editor.ts'
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

test('Writer groups same-path projects by persisted id and keeps all invalid ids in one unmanaged group', () => {
  const groups = buildCoreProjectGroups(
    [
      { id: 'project-a', name: 'A', workRoot: 'E:\\shared' },
      { id: 'project-b', name: 'B', workRoot: 'E:\\shared' },
    ],
    [
      { id: 'session-a', title: 'A', metadata: { project_id: 'project-a' } },
      { id: 'session-b', title: 'B', metadata: { project_id: 'project-b' } },
      { id: 'orphan-a', title: 'Old', metadata: { project_id: 'missing' } },
      { id: 'orphan-b', title: 'Legacy', metadata: { work_root: 'E:\\shared' } },
    ],
  )

  assert.equal(groups.length, 3)
  assert.deepEqual(groups.map((group) => [group.id, group.sessions.map((session) => session.id), group.canManage]), [
    ['project-a', ['session-a'], true],
    ['project-b', ['session-b'], true],
    ['unassigned', ['orphan-a', 'orphan-b'], false],
  ])
})

test('Writer discards stale AGENTS.md reads and saves through the project captured when opening the editor', async () => {
  let currentProjectId = 'project-a'
  let currentToken = 1
  let resolveA!: (value: { content: string; exists: boolean }) => void
  let resolveB!: (value: { content: string; exists: boolean }) => void
  const slowA = new Promise<{ content: string; exists: boolean }>((resolve) => { resolveA = resolve })
  const fastB = new Promise<{ content: string; exists: boolean }>((resolve) => { resolveB = resolve })
  const content: string[] = []

  const load = async (projectId: string, token: number, response: Promise<{ content: string; exists: boolean }>) => {
    const agents = await response
    if (shouldApplyWriterProjectAgents(projectId, token, currentProjectId, currentToken)) {
      content.push(agents.content)
    }
  }
  const loadingA = load('project-a', 1, slowA)
  currentProjectId = 'project-b'
  currentToken = 2
  const loadingB = load('project-b', 2, fastB)
  resolveB({ content: '# B', exists: true })
  await loadingB
  resolveA({ content: '# A', exists: true })
  await loadingA

  const savedProjectIds: string[] = []
  const saveA = createWriterProjectAgentsSaveHandler('project-a', async (projectId, value) => {
    savedProjectIds.push(projectId)
    return { content: value, exists: true }
  })
  currentProjectId = 'project-b'
  await saveA('# edited A')

  assert.deepEqual(content, ['# B'])
  assert.deepEqual(savedProjectIds, ['project-a'])
})

test('Writer keeps the latest AGENTS.md loading state through stale completion and failure', async () => {
  type Result = { content: string; exists: boolean }
  let currentProjectId = 'project-a'
  let currentToken = 1
  let loading = true
  let readyToken = 0
  let content = ''
  let error = ''
  let resolveOld!: (value: Result) => void
  let rejectOld!: (reason: Error) => void
  let resolveNew!: (value: Result) => void
  const oldSuccess = new Promise<Result>((resolve) => { resolveOld = resolve })
  const oldFailure = new Promise<Result>((_resolve, reject) => { rejectOld = reject })
  const newest = new Promise<Result>((resolve) => { resolveNew = resolve })

  const apply = async (projectId: string, token: number, response: Promise<Result>) => {
    try {
      const result = await response
      if (shouldApplyWriterProjectAgents(projectId, token, currentProjectId, currentToken)) {
        content = result.content
        readyToken = token
      }
    } catch {
      if (shouldApplyWriterProjectAgents(projectId, token, currentProjectId, currentToken)) error = '读取 AGENTS.md 失败'
    } finally {
      if (shouldApplyWriterProjectAgents(projectId, token, currentProjectId, currentToken)) loading = false
    }
  }

  const first = apply('project-a', 1, oldSuccess)
  currentProjectId = 'project-b'
  currentToken = 2
  loading = true
  const second = apply('project-b', 2, newest)
  resolveOld({ content: '# stale', exists: true })
  await first
  assert.equal(loading, true)
  assert.equal(readyToken === currentToken, false)

  const failedOld = apply('project-a', 1, oldFailure)
  rejectOld(new Error('stale failed'))
  await failedOld
  assert.equal(loading, true)
  assert.equal(error, '')

  resolveNew({ content: '# current', exists: true })
  await second
  assert.equal(content, '# current')
  assert.equal(error, '')
  assert.equal(loading, false)
  assert.equal(readyToken === currentToken, true)
})
