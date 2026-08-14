import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { createCoreProjectWorkspaceActions } from '../src/projects/workspace'
import type { CoreProjectClient } from '../src/projects/client'
import type { CoreSessionListItem } from '../src/types'
import { buildCoreProjectGroups, type CoreProject } from '../src/projects/types'

const project: CoreProject = { id: 'project-1', name: 'Docs', workRoot: 'E:\\docs' }
const initialSession: CoreSessionListItem = {
  id: 'session-1',
  title: 'Docs',
  createdAt: '',
  metadata: { project_id: 'project-1', work_root: 'E:\\docs' },
}

function createWorkspace() {
  const client = {
    list: vi.fn(),
    create: vi.fn().mockResolvedValue({ project, session: initialSession }),
    get: vi.fn(),
    rename: vi.fn().mockResolvedValue({ ...project, name: 'Documentation' }),
    delete: vi.fn().mockResolvedValue(undefined),
    createSession: vi.fn().mockResolvedValue({
      id: 'session-2',
      title: '新会话',
      metadata: { project_id: 'project-1', work_root: 'E:\\docs' },
    }),
    listSessions: vi.fn(),
    readAgents: vi.fn().mockResolvedValue({ content: '# Existing', exists: true }),
    writeAgents: vi.fn().mockResolvedValue({ content: '# Updated', exists: true }),
    listFiles: vi.fn().mockResolvedValue({ entries: [], path: '' }),
    readFile: vi.fn().mockResolvedValue({ content: '', path: '' }),
    writeFile: vi.fn().mockResolvedValue({ content: '', path: '' }),
    fileRawUrl: vi.fn(() => ''),
    browseDirectory: vi.fn().mockResolvedValue({ entries: [], path: '' }),
  } satisfies CoreProjectClient
  const projects = ref<CoreProject[]>([])
  const sessions = ref<CoreSessionListItem[]>([])
  const activeSessionId = ref<string | null>(null)
  const selectSession = vi.fn().mockResolvedValue(undefined)
  return {
    client,
    projects,
    sessions,
    activeSessionId,
    selectSession,
    actions: createCoreProjectWorkspaceActions({
      client,
      projects,
      sessions,
      activeSessionId,
      selectSession,
    }),
  }
}

describe('Core project workspace grouping', () => {
  it('groups sessions by persisted project and displays its path', () => {
    const groups = buildCoreProjectGroups([project], [initialSession])

    expect(groups[0]).toMatchObject({ id: 'project-1', name: 'Docs', workRoot: 'E:\\docs' })
    expect(groups[0].sessions).toHaveLength(1)
  })

  it('keeps historical sessions without project_id in one explicit compatibility group', () => {
    const groups = buildCoreProjectGroups([], [
      { id: 'old-1', title: 'Legacy one', metadata: { work_root: 'E:\\one' } },
      { id: 'old-2', title: 'Legacy two' },
    ])

    expect(groups).toEqual([expect.objectContaining({ id: 'unassigned', name: 'Unassigned', sessions: expect.any(Array) })])
    expect(groups[0].sessions).toHaveLength(2)
  })
})

describe('Core project demo workspace actions', () => {
  it('creates a project and selects its returned initial session', async () => {
    const workspace = createWorkspace()

    await workspace.actions.createProject({ name: 'Docs', work_root: 'E:\\docs' })

    expect(workspace.client.create).toHaveBeenCalledWith({ name: 'Docs', work_root: 'E:\\docs' })
    expect(workspace.sessions.value).toEqual([expect.objectContaining({ id: 'session-1' })])
    expect(workspace.activeSessionId.value).toBe('session-1')
    expect(workspace.selectSession).toHaveBeenCalledWith('session-1')
  })

  it('creates project sessions with persisted project metadata and blocks duplicate work', async () => {
    const workspace = createWorkspace()
    workspace.projects.value = [project]
    let release!: () => void
    workspace.client.createSession.mockImplementationOnce(() => new Promise((resolve) => {
      release = () => resolve({ id: 'session-2', title: '新会话', metadata: {} })
    }))

    const first = workspace.actions.createProjectSession('project-1')
    const second = workspace.actions.createProjectSession('project-1')

    expect(workspace.actions.busyProjectIds.value).toEqual(['project-1'])
    expect(workspace.client.createSession).toHaveBeenCalledTimes(1)
    expect(workspace.client.createSession).toHaveBeenCalledWith('project-1', '新会话')
    release()
    await Promise.all([first, second])
    expect(workspace.actions.busyProjectIds.value).toEqual([])
  })

  it('routes rename, AGENTS.md reads and writes, and safe deletion through the project client', async () => {
    const workspace = createWorkspace()
    workspace.projects.value = [project]
    workspace.sessions.value = [initialSession]
    workspace.activeSessionId.value = 'session-1'

    await expect(workspace.actions.renameProject('project-1', 'Documentation')).resolves.toMatchObject({ name: 'Documentation' })
    await expect(workspace.actions.readAgents('project-1')).resolves.toEqual({ content: '# Existing', exists: true })
    await expect(workspace.actions.writeAgents('project-1', '# Updated')).resolves.toEqual({ content: '# Updated', exists: true })
    await expect(workspace.actions.deleteProject('project-1')).resolves.toMatchObject({ wasActive: true, deletedSessionIds: ['session-1'] })

    expect(workspace.client.rename).toHaveBeenCalledWith('project-1', 'Documentation')
    expect(workspace.client.readAgents).toHaveBeenCalledWith('project-1')
    expect(workspace.client.writeAgents).toHaveBeenCalledWith('project-1', '# Updated')
    expect(workspace.client.delete).toHaveBeenCalledWith('project-1')
  })
})
