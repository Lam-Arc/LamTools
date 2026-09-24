import { beforeEach, describe, expect, it, vi } from 'vitest'

const invoke = vi.fn()

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invoke(...args),
}))

const { callEmbeddedStudy, listEmbeddedStudySkills, runEmbeddedSundayTurn, resumeEmbeddedSundayTurn } = await import('../src/native/rustAgent')

beforeEach(() => {
  invoke.mockReset()
})

describe('callEmbeddedStudy', () => {
  it('reads the native skill inventory rather than inventing skill locations in the UI', async () => {
    const skills = [{ name: 'curate-notes', description: 'Study notes', location: 'bundled://study/future/curate-notes/SKILL.md' }]
    invoke.mockResolvedValue(skills)
    expect(await listEmbeddedStudySkills()).toEqual(skills)
    expect(invoke).toHaveBeenCalledWith('sunday_study_skill_catalog')
  })

  it('forwards Study and skill switches on both initial turns and approval continuations', async () => {
    const shared = {
      sessionId: 'study-session', projectId: 'study-project', apiKey: 'test-key',
      provider: { api_type: 'openai', base_url: 'https://model.invalid/v1', name: 'Test' } as never,
      model: { model_id: 'test-model' } as never,
      study: { enabled: true }, disabledSkillNames: ['teach'],
    }
    invoke.mockResolvedValue({ status: 'completed' })
    await runEmbeddedSundayTurn({ ...shared, turnId: 'turn-1', modelRecordId: 'model-1', history: [] })
    await resumeEmbeddedSundayTurn({ ...shared, continuation: {} as never, requestId: 'approval-1', decision: 'approve_once', guidance: '' })
    for (const [command, args] of invoke.mock.calls) {
      expect(['sunday_agent_turn', 'sunday_agent_resume']).toContain(command)
      expect(args.payload).toMatchObject({ studyTools: true, disabledSkillNames: ['teach'] })
    }
    expect(invoke).toHaveBeenCalledTimes(2)
  })
  it('forwards the host-owned Study payload to the native command', async () => {
    invoke.mockResolvedValue({ revision: 2 })
    const result = await callEmbeddedStudy({
      method: 'study.get',
      params: { limit: 5 },
      sessionMetadata: { study_scope: 'map' },
      sessionTargets: { 'study:main': { id: 'study:main', title: '知识图谱' } },
    })

    expect(result).toEqual({ revision: 2 })
    expect(invoke).toHaveBeenCalledWith('sunday_study_rpc', {
      payload: {
        method: 'study.get',
        params: { limit: 5 },
        sessionMetadata: { study_scope: 'map' },
        sessionTargets: { 'study:main': { id: 'study:main', title: '知识图谱' } },
        provider: undefined,
        // The host always supplies the retry policy slot; Rust defaults it.
        retryConfig: {},
      },
    })
  })

  it('forwards the configured model retry policy for Study text actions', async () => {
    invoke.mockResolvedValue({ ok: true })
    const retryConfig = { max_attempts: 3, retry_delays_seconds: [1, 2] }
    await callEmbeddedStudy({ method: 'study.text', params: { id: 'mark-1' }, retryConfig })

    expect(invoke.mock.calls[0][1]).toMatchObject({
      payload: { method: 'study.text', retryConfig },
    })
  })

  it('passes the provider only for text actions that need a model', async () => {
    invoke.mockResolvedValue({ mark: { id: 'mark-1' } })
    await callEmbeddedStudy({
      method: 'study.text',
      params: { id: 'mark-1', action: 'explain' },
      provider: {
        provider: { api_type: 'openai', base_url: 'https://model.invalid/v1', name: 'Test' } as never,
        model: { model_id: 'text-model' } as never,
        apiKey: 'secret',
      },
    })

    const payload = invoke.mock.calls[0][1] as { payload: Record<string, unknown> }
    expect(payload.payload.provider).toEqual(expect.objectContaining({
      apiType: 'openai',
      apiKey: 'secret',
      apiModelId: 'text-model',
    }))
  })

  it('keeps structured Study failures readable by the shared UI', async () => {
    invoke.mockRejectedValue(JSON.stringify({ error: 'STALE_CURSOR', reason: 'CURSOR_REVISION' }))
    await expect(callEmbeddedStudy({ method: 'study.get' }))
      .rejects.toMatchObject({
        message: 'STALE_CURSOR',
        reason: 'CURSOR_REVISION',
        method: 'study.get',
      })
  })

  it('surfaces a plain transport failure with its own message', async () => {
    invoke.mockRejectedValue('failed to open the study database')
    await expect(callEmbeddedStudy({ method: 'study.get' }))
      .rejects.toMatchObject({
        message: 'failed to open the study database',
        method: 'study.get',
      })
  })
})
