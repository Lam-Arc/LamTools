import {
  CORE_PROJECT_COLOR_KEYS,
  CORE_PROJECT_ICON_KEYS,
  DEFAULT_CORE_PROJECT_COLOR_KEY,
  DEFAULT_CORE_PROJECT_ICON_KEY,
  type CoreProject,
  type CoreProjectClient,
  type CoreProjectColorKey,
  type CoreProjectIconKey,
  type CoreProjectSession,
} from '@lamtools/ui'
import type { LocalRepository } from './LocalRepository'

/** Read-heavy project facade: navigation reads local state, while mutations
 * and file operations continue to use the authenticated remote client. */
export function createLocalFirstProjectClient(
  remote: CoreProjectClient,
  repository: LocalRepository,
): CoreProjectClient {
  return {
    ...remote,
    async list(): Promise<CoreProject[]> {
      const projects = await repository.listProjects()
      return projects.map((project) => ({
        id: project.id,
        name: project.name,
        workRoot: project.workRoot || project.path,
        iconKey: validIconKey(project.iconKey),
        colorKey: validColorKey(project.colorKey),
        createdAt: project.createdAt,
        updatedAt: project.updatedAt,
      }))
    },
    async listSessions(projectId: string): Promise<CoreProjectSession[]> {
      const sessions = await repository.listSessions(projectId)
      return sessions.map((session) => ({
        id: session.id,
        title: session.title,
        createdAt: session.createdAt,
        updatedAt: session.updatedAt,
        status: session.status,
        metadata: session.metadata,
      }))
    },
  }
}

function validIconKey(value: string): CoreProjectIconKey {
  return CORE_PROJECT_ICON_KEYS.includes(value as CoreProjectIconKey)
    ? value as CoreProjectIconKey
    : DEFAULT_CORE_PROJECT_ICON_KEY
}

function validColorKey(value: string): CoreProjectColorKey {
  return CORE_PROJECT_COLOR_KEYS.includes(value as CoreProjectColorKey)
    ? value as CoreProjectColorKey
    : DEFAULT_CORE_PROJECT_COLOR_KEY
}
