import type { ProjectGroup, SessionItem } from '@/types.ts'

export const CORE_PROJECT_ICON_KEYS = [
  'folder',
  'code',
  'idea',
  'design',
  'docs',
  'work',
  'rocket',
  'sparkles',
] as const

export const CORE_PROJECT_SOLID_COLOR_KEYS = [
  'gray',
  'blue',
  'violet',
  'pink',
  'red',
  'orange',
  'green',
  'cyan',
] as const

export const CORE_PROJECT_GRADIENT_COLOR_KEYS = [
  'sunrise',
  'aurora',
  'ocean',
  'violet-sky',
  'berry',
  'ember',
  'forest',
  'prism',
] as const

export const CORE_PROJECT_COLOR_KEYS = [
  ...CORE_PROJECT_SOLID_COLOR_KEYS,
  ...CORE_PROJECT_GRADIENT_COLOR_KEYS,
] as const

export const DEFAULT_CORE_PROJECT_ICON_KEY = 'folder'
export const DEFAULT_CORE_PROJECT_COLOR_KEY = 'gray'

export type CoreProjectIconKey = typeof CORE_PROJECT_ICON_KEYS[number]
export type CoreProjectColorKey = typeof CORE_PROJECT_COLOR_KEYS[number]

export interface CoreProject {
  id: string
  name: string
  workRoot: string
  iconKey: CoreProjectIconKey
  colorKey: CoreProjectColorKey
  createdAt?: string
  updatedAt?: string
}

export interface CoreProjectCreatePayload {
  name: string
  work_root: string
  icon_key?: CoreProjectIconKey
  color_key?: CoreProjectColorKey
}

export interface CoreProjectUpdatePayload {
  name?: string
  icon_key?: CoreProjectIconKey
  color_key?: CoreProjectColorKey
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
  iconKey: CoreProjectIconKey
  colorKey: CoreProjectColorKey
}

export function buildCoreProjectGroups(
  projects: CoreProject[],
  sessions: CoreProjectSession[],
): CoreProjectGroup[] {
  const groups: CoreProjectGroup[] = projects.map((project) => ({
    id: project.id,
    name: project.name,
    workRoot: project.workRoot,
    iconKey: project.iconKey,
    colorKey: project.colorKey,
    sessions: [] as SessionItem[],
    canManage: true,
  }))
  const groupsByWorkRoot = new Map(groups.map((group) => [group.workRoot, group]))
  const groupsById = new Map(groups.map((group) => [group.id, group]))
  for (const session of sessions) {
    // A session's owning project is a fact the core already states as `project_id`.
    // Filing by work_root instead used to leave every project empty on any core
    // that reports the id but no metadata, and the sidebar then claimed the project
    // had no sessions while the list endpoint was returning them. The directory is
    // kept as a fallback for cores that only report where the session ran.
    const byId = session.project_id ? groupsById.get(session.project_id) : undefined
    const workRoot = typeof session.metadata?.work_root === 'string'
      ? session.metadata.work_root
      : ''
    const group = byId ?? (workRoot ? groupsByWorkRoot.get(workRoot) : undefined)
    if (group) {
      group.sessions.push(session)
    }
  }

  return groups
}
