import { computed, ref, type Ref } from 'vue'

import type { CoreSessionListItem } from '../types'
import type { CoreProjectClient } from './client'
import type {
  CoreProject,
  CoreProjectAgents,
  CoreProjectCreatePayload,
  CoreProjectCreateResult,
} from './types'

export interface CoreProjectWorkspaceOptions {
  client: CoreProjectClient
  projects: Ref<CoreProject[]>
  sessions: Ref<CoreSessionListItem[]>
  activeSessionId: Ref<string | null>
  selectSession(sessionId: string): Promise<void>
}

export function createCoreProjectWorkspaceActions(options: CoreProjectWorkspaceOptions) {
  const busyIds = ref(new Set<string>())
  const busyProjectIds = computed(() => [...busyIds.value])

  return {
    busyProjectIds,
    createProject: async (payload: CoreProjectCreatePayload): Promise<CoreProjectCreateResult> => {
      const created = await options.client.create(payload)
      options.projects.value = upsertById(options.projects.value, created.project)
      const session = toSessionItem(created.session)
      options.sessions.value = upsertById(options.sessions.value, session)
      options.activeSessionId.value = session.id
      await options.selectSession(session.id)
      return created
    },
    createProjectSession: async (projectId: string): Promise<CoreSessionListItem | undefined> => {
      if (busyIds.value.has(projectId)) return undefined
      if (!options.projects.value.some((item) => item.id === projectId)) return undefined

      busyIds.value = new Set([...busyIds.value, projectId])
      try {
        const session = toSessionItem(await options.client.createSession(projectId, '新会话'))
        options.sessions.value = upsertById(options.sessions.value, session)
        options.activeSessionId.value = session.id
        await options.selectSession(session.id)
        return session
      } finally {
        const next = new Set(busyIds.value)
        next.delete(projectId)
        busyIds.value = next
      }
    },
    renameProject: async (projectId: string, name: string): Promise<CoreProject> => {
      const updated = await options.client.rename(projectId, name)
      options.projects.value = upsertById(options.projects.value, updated)
      return updated
    },
    readAgents: async (projectId: string): Promise<CoreProjectAgents> => options.client.readAgents(projectId),
    writeAgents: async (projectId: string, content: string): Promise<CoreProjectAgents> => (
      options.client.writeAgents(projectId, content)
    ),
    deleteProject: async (projectId: string) => {
      const project = options.projects.value.find((item) => item.id === projectId)
      if (!project) return undefined
      const deletedSessionIds = options.sessions.value
        .filter((session) => session.metadata?.work_root === project.workRoot)
        .map((session) => session.id)
      const wasActive = Boolean(options.activeSessionId.value && deletedSessionIds.includes(options.activeSessionId.value))

      await options.client.delete(project.id)
      options.projects.value = options.projects.value.filter((item) => item.id !== project.id)
      options.sessions.value = options.sessions.value.filter((session) => !deletedSessionIds.includes(session.id))
      if (wasActive) options.activeSessionId.value = null

      return { project, deletedSessionIds, wasActive }
    },
  }
}

function toSessionItem(session: CoreProjectCreateResult['session']): CoreSessionListItem {
  return {
    id: session.id,
    title: session.title || session.id,
    createdAt: session.createdAt || '',
    updatedAt: session.updatedAt,
    status: session.status,
    metadata: session.metadata,
  }
}

function upsertById<T extends { id: string }>(items: T[], item: T): T[] {
  return [item, ...items.filter((current) => current.id !== item.id)]
}
