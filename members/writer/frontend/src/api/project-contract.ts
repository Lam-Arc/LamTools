export interface ProjectAgents {
  content: string
  exists: boolean
}

export function normalizeProjectAgents(payload: { agents_md?: unknown }): ProjectAgents {
  const agents = payload.agents_md
  if (!agents || typeof agents !== 'object') return { content: '', exists: false }
  const record = agents as Record<string, unknown>
  return {
    content: typeof record.content === 'string' ? record.content : '',
    exists: record.exists === true,
  }
}

export function requireProjectCreateResult<TProject, TSession>(payload: {
  project?: TProject
  session?: TSession
}): { project: TProject; session: TSession } {
  if (!payload.project || !payload.session) {
    throw new Error('project.create response is missing project or session')
  }
  return { project: payload.project, session: payload.session }
}
