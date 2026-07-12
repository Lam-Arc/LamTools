import { computed, ref, shallowRef } from 'vue'

export interface CoreOwnedProject { id: string }
export interface CoreOwnedSession { id: string; project_id?: string | null }

export interface CoreProjectSessionAdapter<Project extends CoreOwnedProject, Session extends CoreOwnedSession, ProjectCreate, ProjectUpdate, SessionCreate, SessionUpdate> {
  listProjects(): Promise<Project[]>
  createProject(data: ProjectCreate): Promise<{ project: Project; session: Session }>
  updateProject(id: string, data: ProjectUpdate): Promise<Project>
  deleteProject(id: string): Promise<void>
  createProjectSession(projectId: string, title?: string): Promise<Session>
  readAgents(projectId: string): Promise<{ content: string; exists: boolean }>
  writeAgents(projectId: string, content: string): Promise<{ content: string; exists: boolean }>
  listSessions(projectId?: string): Promise<Session[]>
  createSession(data: SessionCreate): Promise<Session>
  updateSession(id: string, data: SessionUpdate): Promise<Session>
  deleteSession(id: string): Promise<void>
}

export function useCoreProjectSessionState<Project extends CoreOwnedProject, Session extends CoreOwnedSession, ProjectCreate, ProjectUpdate, SessionCreate, SessionUpdate>(
  adapter: CoreProjectSessionAdapter<Project, Session, ProjectCreate, ProjectUpdate, SessionCreate, SessionUpdate>,
) {
  const projects = shallowRef<Project[]>([])
  const sessions = shallowRef<Session[]>([])
  const activeProject = shallowRef<Project | null>(null)
  const activeSession = shallowRef<Session | null>(null)
  const projectsLoading = ref(false)
  const sessionsLoading = ref(false)
  const activeProjectId = computed(() => activeProject.value?.id ?? null)
  const activeSessionId = computed(() => activeSession.value?.id ?? null)
  const sessionsByProject = computed(() => {
    const result = new Map<string, Session[]>()
    for (const session of sessions.value) {
      const projectId = session.project_id || '__none__'
      result.set(projectId, [...(result.get(projectId) || []), session])
    }
    return result
  })

  async function fetchProjects() {
    projectsLoading.value = true
    try { projects.value = await adapter.listProjects() } finally { projectsLoading.value = false }
  }
  async function createProject(data: ProjectCreate) {
    const result = await adapter.createProject(data)
    projects.value = upsert(projects.value, result.project)
    sessions.value = upsert(sessions.value, result.session, true)
    return result
  }
  async function updateProject(id: string, data: ProjectUpdate) {
    const project = await adapter.updateProject(id, data)
    projects.value = upsert(projects.value, project)
    if (activeProject.value?.id === id) activeProject.value = project
    return project
  }
  async function deleteProject(id: string) {
    await adapter.deleteProject(id)
    projects.value = projects.value.filter(project => project.id !== id)
    removeSessions(sessions.value.filter(session => session.project_id === id).map(session => session.id))
    if (activeProject.value?.id === id) activeProject.value = null
  }
  async function createProjectSession(projectId: string, title = 'New Session') {
    const session = await adapter.createProjectSession(projectId, title)
    sessions.value = upsert(sessions.value, session, true)
    return session
  }
  async function fetchSessions(projectId?: string) {
    sessionsLoading.value = true
    try { sessions.value = await adapter.listSessions(projectId) } finally { sessionsLoading.value = false }
  }
  async function createSession(data: SessionCreate) {
    const session = await adapter.createSession(data)
    sessions.value = upsert(sessions.value, session, true)
    return session
  }
  async function updateSession(id: string, data: SessionUpdate) {
    const session = await adapter.updateSession(id, data)
    sessions.value = upsert(sessions.value, session)
    if (activeSession.value?.id === id) activeSession.value = session
    return session
  }
  async function deleteSession(id: string) {
    await adapter.deleteSession(id)
    removeSessions([id])
  }
  function removeSessions(ids: Iterable<string>) {
    const removed = new Set(ids)
    sessions.value = sessions.value.filter(session => !removed.has(session.id))
    if (activeSession.value && removed.has(activeSession.value.id)) activeSession.value = null
  }
  function updateSessionField(id: string, patch: Partial<Session>) {
    const current = sessions.value.find(session => session.id === id)
    if (!current) return
    const updated = { ...current, ...patch }
    sessions.value = upsert(sessions.value, updated)
    if (activeSession.value?.id === id) activeSession.value = updated
  }

  return {
    projects, sessions, activeProject, activeSession, activeProjectId, activeSessionId,
    sessionsByProject, projectsLoading, sessionsLoading, fetchProjects, createProject,
    updateProject, deleteProject, createProjectSession, fetchAgents: adapter.readAgents,
    saveAgents: adapter.writeAgents, fetchSessions, createSession, updateSession, deleteSession,
    removeSessions, updateSessionField,
    selectProject: (project: Project | null) => { activeProject.value = project },
    selectSession: (session: Session | null) => { activeSession.value = session },
  }
}

function upsert<T extends { id: string }>(items: T[], item: T, prepend = false): T[] {
  const index = items.findIndex(candidate => candidate.id === item.id)
  if (index >= 0) return items.map(candidate => candidate.id === item.id ? item : candidate)
  return prepend ? [item, ...items] : [...items, item]
}
