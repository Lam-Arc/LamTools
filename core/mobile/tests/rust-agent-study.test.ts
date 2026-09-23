import { beforeEach, describe, expect, it, vi } from 'vitest'

const invoke = vi.fn()

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invoke(...args),
}))

const { callEmbeddedStudy } = await import('../src/native/rustAgent')

beforeEach(() => {
  invoke.mockReset()
})

describe('callEmbeddedStudy', () => {
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
      },
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
