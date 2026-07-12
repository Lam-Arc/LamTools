import { describe, expect, it } from 'vitest'
import { useCoreConfigState } from '../src/composables/useCoreConfigState'
import { useCoreProjectSessionState } from '../src/composables/useCoreProjectSessionState'

describe('Core shared member state', () => {
  it('owns provider and model collection updates behind an adapter', async () => {
    const state = useCoreConfigState({
      listProviders: async () => [{ id: 'p1' }],
      createProvider: async () => ({ id: 'p2' }),
      updateProvider: async (id) => ({ id }),
      deleteProvider: async () => undefined,
      listModels: async () => [{ id: 'm1' }],
      createModel: async () => ({ id: 'm2' }),
      updateModel: async (id) => ({ id }),
      deleteModel: async () => undefined,
    })
    await state.fetchProviders()
    await state.createProvider({})
    await state.fetchModels()
    await state.deleteModel('m1')
    expect(state.providers.value.map(item => item.id)).toEqual(['p2', 'p1'])
    expect(state.models.value).toEqual([])
  })

  it('keeps project and session ownership state consistent', async () => {
    const state = useCoreProjectSessionState({
      listProjects: async () => [{ id: 'p1' }],
      createProject: async () => ({ project: { id: 'p2' }, session: { id: 's2', project_id: 'p2' } }),
      updateProject: async (id) => ({ id }),
      deleteProject: async () => undefined,
      createProjectSession: async (projectId) => ({ id: 's3', project_id: projectId }),
      readAgents: async () => ({ content: '', exists: false }),
      writeAgents: async (_id, content) => ({ content, exists: true }),
      listSessions: async () => [{ id: 's1', project_id: 'p1' }],
      createSession: async () => ({ id: 's4' }),
      updateSession: async (id) => ({ id, project_id: 'p1' }),
      deleteSession: async () => undefined,
    })
    await state.fetchProjects()
    await state.fetchSessions()
    await state.createProject({})
    await state.deleteProject('p1')
    expect(state.projects.value.map(item => item.id)).toEqual(['p2'])
    expect(state.sessions.value.map(item => item.id)).toEqual(['s2'])
  })
})
