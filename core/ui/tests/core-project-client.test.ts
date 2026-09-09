import { afterEach, describe, expect, it, vi } from 'vitest'

import { createCoreProjectClient } from '../src/projects/client'
import { createDirectTransport } from '../src/transport/directTransport'

describe('Core project client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('maps the project REST contract without a product-specific API layer', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ projects: [{ id: 'project-1', name: 'Docs', work_root: 'E:\\docs' }] }))
      .mockResolvedValueOnce(jsonResponse({
        project: { id: 'project-1', name: 'Docs', work_root: 'E:\\docs' },
        session: { id: 'session-1', title: 'Docs', metadata: { project_id: 'project-1' } },
      }))
      .mockResolvedValueOnce(jsonResponse({ id: 'project-1', name: 'Docs', work_root: 'E:\\docs' }))
      .mockResolvedValueOnce(jsonResponse({ id: 'project-1', name: 'Documentation', work_root: 'E:\\docs' }))
      .mockResolvedValueOnce(jsonResponse({ sessions: [{ id: 'session-1', title: 'Docs' }] }))
      .mockResolvedValueOnce(jsonResponse({ content: '# Instructions', exists: true }))
      .mockResolvedValueOnce(jsonResponse({ content: '# Updated', exists: true }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetch)

    const client = createCoreProjectClient(createDirectTransport({ apiBase: '/api/core/', fetchImpl: fetch }))

    await expect(client.list()).resolves.toEqual([{ id: 'project-1', name: 'Docs', workRoot: 'E:\\docs' }])
    await expect(client.create({ name: 'Docs', work_root: 'E:\\docs' })).resolves.toMatchObject({
      project: { id: 'project-1', workRoot: 'E:\\docs' },
      session: { id: 'session-1' },
    })
    await expect(client.get('project-1')).resolves.toMatchObject({ id: 'project-1', name: 'Docs' })
    await expect(client.rename('project-1', 'Documentation')).resolves.toMatchObject({ name: 'Documentation' })
    await expect(client.listSessions('project-1')).resolves.toEqual([{ id: 'session-1', title: 'Docs' }])
    await expect(client.readAgents('project-1')).resolves.toEqual({ content: '# Instructions', exists: true })
    await expect(client.writeAgents('project-1', '# Updated')).resolves.toEqual({ content: '# Updated', exists: true })
    await expect(client.delete('project-1')).resolves.toBeUndefined()

    expect(fetchCalls(fetch)).toEqual(expect.arrayContaining([
      { url: '/api/core/projects', method: 'GET' },
      { url: '/api/core/projects', method: 'POST', body: { name: 'Docs', work_root: 'E:\\docs' } },
      { url: '/api/core/projects/project-1', method: 'GET' },
      { url: '/api/core/projects/project-1', method: 'PATCH', body: { name: 'Documentation' } },
      { url: '/api/core/projects/project-1/sessions', method: 'GET' },
      { url: '/api/core/projects/project-1/agents-md', method: 'GET' },
      { url: '/api/core/projects/project-1/agents-md', method: 'PUT', body: { content: '# Updated' } },
      { url: '/api/core/projects/project-1', method: 'DELETE' },
    ]))
  })

  it('reports the backend response when an operation fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Project is active', { status: 409 })))

    await expect(createCoreProjectClient(createDirectTransport({ apiBase: '/api/core', fetchImpl: fetch })).delete('project-1'))
      .rejects.toThrow('Project is active')
  })
})

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function fetchCalls(fetch: ReturnType<typeof vi.fn>): Array<{ url: string; method: string; body?: unknown }> {
  return fetch.mock.calls.map(([url, init]) => ({
    url: String(url),
    method: String((init as RequestInit | undefined)?.method || 'GET'),
    ...decodeBody((init as RequestInit | undefined)?.body),
  }))
}

function decodeBody(body: BodyInit | null | undefined): { body?: unknown } {
  if (body == null) return {}
  if (ArrayBuffer.isView(body)) {
    const bytes = new Uint8Array(body.buffer, body.byteOffset, body.byteLength)
    const text = new TextDecoder().decode(bytes)
    return { body: JSON.parse(text) }
  }
  if (body instanceof ArrayBuffer) {
    return { body: JSON.parse(new TextDecoder().decode(new Uint8Array(body))) }
  }
  return { body: JSON.parse(String(body)) }
}
