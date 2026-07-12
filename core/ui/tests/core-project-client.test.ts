import { afterEach, describe, expect, it, vi } from 'vitest'

import { createCoreProjectClient } from '../src/projects/client'

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

    const client = createCoreProjectClient('/api/core/')

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

    expect(fetch.mock.calls).toEqual(expect.arrayContaining([
      ['/api/core/projects', expect.objectContaining({ method: 'GET' })],
      ['/api/core/projects', expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: 'Docs', work_root: 'E:\\docs' }) })],
      ['/api/core/projects/project-1', expect.objectContaining({ method: 'GET' })],
      ['/api/core/projects/project-1', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ name: 'Documentation' }) })],
      ['/api/core/projects/project-1/sessions', expect.objectContaining({ method: 'GET' })],
      ['/api/core/projects/project-1/agents-md', expect.objectContaining({ method: 'GET' })],
      ['/api/core/projects/project-1/agents-md', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ content: '# Updated' }) })],
      ['/api/core/projects/project-1', expect.objectContaining({ method: 'DELETE' })],
    ]))
  })

  it('reports the backend response when an operation fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Project is active', { status: 409 })))

    await expect(createCoreProjectClient('/api/core').delete('project-1'))
      .rejects.toThrow('Project is active')
  })
})

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
