import type { ProjectGroup, SessionItem } from '../types'

export interface CoreProject {
  id: string
  name: string
  workRoot: string
  createdAt?: string
  updatedAt?: string
}

export interface CoreProjectCreatePayload {
  name: string
  work_root: string
}

export interface CoreProjectSession extends SessionItem {
  metadata?: Record<string, unknown>
}

export interface CoreProjectAgents {
  content: string
  exists: boolean
}

export interface CoreProjectCreateResult {
  project: CoreProject
  session: CoreProjectSession
}

export interface CoreProjectGroup extends ProjectGroup {
  canManage: boolean
}

export function buildCoreProjectGroups(
  projects: CoreProject[],
  sessions: CoreProjectSession[],
): CoreProjectGroup[] {
  const groups: CoreProjectGroup[] = projects.map((project) => ({
    id: project.id,
    name: project.name,
    workRoot: project.workRoot,
    sessions: [] as SessionItem[],
    canManage: true,
  }))
  const groupsByWorkRoot = new Map(groups.map((group) => [group.workRoot, group]))
  const unassigned: SessionItem[] = []

  for (const session of sessions) {
    const workRoot = typeof session.metadata?.work_root === 'string'
      ? session.metadata.work_root
      : ''
    const group = workRoot ? groupsByWorkRoot.get(workRoot) : undefined
    if (group) {
      group.sessions.push(session)
    } else {
      unassigned.push(session)
    }
  }

  if (unassigned.length > 0) {
    groups.push({
      id: 'unassigned',
      name: 'Unassigned',
      sessions: unassigned,
      canManage: false,
    })
  }

  return groups
}
