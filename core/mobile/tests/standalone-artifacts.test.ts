import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { artifactRpc, handleStandaloneArtifactHttp } from '../src/standalone/StandaloneArtifacts'

const ARTIFACT = {
  artifact_id: 'artifact-1',
  project_id: 'p1',
  name: 'notes.md',
  path: 'workspace://notes.md',
  mime_type: 'text/markdown',
  source: 'agent_generated',
  role: 'deliverable',
  latest_revision_id: 'rev-2',
  revision_count: 2,
  thread_id: 'thread-1',
  turn_id: 'turn-1',
  item_id: 'item-1',
  tool_name: 'write_file',
  deleted: false,
  created_at: '2026-09-24T00:00:00Z',
  updated_at: '2026-09-24T00:00:00Z',
}

afterEach(() => { invokeMock.mockReset(); vi.unstubAllGlobals() })

describe('standalone artifacts', () => {
  it('answers the panel RPCs with the desktop payload shapes', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
      if (command === 'sunday_artifact_list') return { artifacts: [ARTIFACT] }
      if (command === 'sunday_artifact_revisions') {
        return {
          artifact: ARTIFACT,
          revisions: [
            { revision_id: 'rev-2', artifact_id: 'artifact-1', ordinal: 2, blob_hash: 'b'.repeat(64), size: 4, mime_type: 'text/markdown', restored_from_revision_id: '', created_at: 'now' },
            { revision_id: 'rev-1', artifact_id: 'artifact-1', ordinal: 1, blob_hash: 'a'.repeat(64), size: 2, mime_type: 'text/markdown', restored_from_revision_id: '', created_at: 'before' },
          ],
        }
      }
      if (command === 'sunday_artifact_set_deleted') {
        expect(args.artifactIds).toEqual(['artifact-1'])
        return args.deleted ? { deleted: 1 } : { restored: 1 }
      }
      if (command === 'sunday_artifact_restore_revision') return { artifact: { ...ARTIFACT, revision_count: 3 } }
      throw new Error(`unexpected ${command}`)
    })

    expect(await artifactRpc('artifact.list', { project_id: 'p1' })).toEqual({ artifacts: [ARTIFACT] })
    // include_deleted reaches the host, or a soft-deleted artifact stays hidden.
    await artifactRpc('artifact.list', { project_id: 'p1', include_deleted: true })
    expect(invokeMock).toHaveBeenCalledWith('sunday_artifact_list', { projectId: 'p1', includeDeleted: true })

    expect(await artifactRpc('artifact.read', { project_id: 'p1', artifact_id: 'artifact-1' }))
      .toEqual({ artifact: ARTIFACT })
    expect(await artifactRpc('artifact.show', { project_id: 'p1', artifact_id: 'artifact-1' }))
      .toEqual({ artifact: ARTIFACT })
    const revisions = await artifactRpc('artifact.revisions', { project_id: 'p1', artifact_id: 'artifact-1' })
    expect((revisions?.revisions as unknown[]).length).toBe(2)
    expect(await artifactRpc('artifact.delete', { project_id: 'p1', artifact_ids: ['artifact-1'] }))
      .toEqual({ deleted: 1 })
    expect(await artifactRpc('artifact.restore', { project_id: 'p1', artifact_ids: ['artifact-1'] }))
      .toEqual({ restored: 1 })
    expect(await artifactRpc('artifact.revision.restore', {
      project_id: 'p1', artifact_id: 'artifact-1', revision_id: 'rev-1',
    })).toEqual({ artifact: { ...ARTIFACT, revision_count: 3 } })

    // Structural failures must be loud, and other methods must fall through.
    await expect(artifactRpc('artifact.list', {})).rejects.toThrow('project_id is required')
    await expect(artifactRpc('artifact.delete', { project_id: 'p1' })).rejects.toThrow('artifact_ids is required')
    await expect(artifactRpc('artifact.revision.restore', { project_id: 'p1', artifact_id: 'a' }))
      .rejects.toThrow('revision_id is required')
    expect(await artifactRpc('session.permissions.set', {})).toBeNull()
  })

  it('serves the artifact file route the message views call', async () => {
    const bytes = Uint8Array.of(1, 2, 3, 4)
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
      if (command !== 'sunday_artifact_file') throw new Error(`unexpected ${command}`)
      if (args.artifactId !== 'artifact-1') return null
      return {
        path: 'workspace://image.png',
        mimeType: 'image/png',
        dataBase64: Buffer.from(bytes).toString('base64'),
      }
    })

    const response = await handleStandaloneArtifactHttp({
      kind: 'http',
      method: 'GET',
      path: '/projects/p1/artifacts/artifact-1/file?revision_id=rev-1',
    })
    expect(response?.status).toBe(200)
    expect(response?.headers['Content-Type']).toBe('image/png')
    expect(Array.from(response!.body)).toEqual(Array.from(bytes))
    expect(invokeMock).toHaveBeenCalledWith('sunday_artifact_file', {
      projectId: 'p1', artifactId: 'artifact-1', revisionId: 'rev-1',
    })

    // A missing artifact is 404, and other paths are not ours.
    const missing = await handleStandaloneArtifactHttp({
      kind: 'http', method: 'GET', path: '/projects/p1/artifacts/gone/file',
    })
    expect(missing?.status).toBe(404)
    expect(await handleStandaloneArtifactHttp({
      kind: 'http', method: 'GET', path: '/projects/p1/files/raw?path=a.txt',
    })).toBeNull()
    expect(await handleStandaloneArtifactHttp({
      kind: 'http', method: 'POST', path: '/projects/p1/artifacts/artifact-1/file',
    })).toBeNull()
  })
})
