import { defineStore } from 'pinia'
import { useCoreProjectSessionState, type CoreProjectSessionAdapter } from '@lamtools/ui'
import * as api from '@/api'
import type { Project, ProjectCreate, ProjectUpdate, Session, SessionCreate, SessionUpdate } from '@/types'

const adapter: CoreProjectSessionAdapter<Project, Session, ProjectCreate, ProjectUpdate, SessionCreate, SessionUpdate> = {
  listProjects: api.listProjects,
  createProject: api.createProject,
  updateProject: api.updateProject,
  deleteProject: api.deleteProject,
  createProjectSession: api.createProjectSession,
  readAgents: api.getAgentsMd,
  writeAgents: api.updateAgentsMd,
  listSessions: async (projectId) => projectId ? api.listProjectSessions(projectId) : api.listSessions(),
  createSession: api.createSession,
  updateSession: api.updateSession,
  deleteSession: api.deleteSession,
}

export const useWorkspaceStore = defineStore('workspace', () => useCoreProjectSessionState(adapter))
