import type { CoreProjectClient } from '@lamtools/ui'
import type { CoreProject, CoreProjectSession } from '@lamtools/ui'
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
