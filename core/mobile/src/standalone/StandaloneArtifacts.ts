import type { TransportHttpRequest, TransportHttpResponse } from '@lamtools/ui'
import {
  hasEmbeddedRustCore,
  readEmbeddedArtifactFile,
  setEmbeddedArtifactsDeleted,
  openEmbeddedArtifact,
  listEmbeddedArtifacts,
  type EmbeddedArtifact,
} from '../native/rustAgent'

/** Every artifact of one project, including soft-deleted ones when asked. */
export async function listStandaloneArtifacts(
  projectId: string,
  includeDeleted: boolean,
): Promise<EmbeddedArtifact[]> {
  if (!hasEmbeddedRustCore()) return []
  return await listEmbeddedArtifacts(projectId, includeDeleted)
}

export async function artifactRpc(
  method: string,
  params: Record<string, unknown>,
): Promise<Record<string, unknown> | null> {
  const projectId = String(params.project_id || params.projectId || '')
  const artifactId = String(params.artifact_id || params.artifactId || '')
  if (method === 'artifact.list') {
    if (!projectId) throw new Error('project_id is required')
    return { artifacts: await listStandaloneArtifacts(projectId, Boolean(params.include_deleted)) }
  }
  if (method === 'artifact.read' || method === 'artifact.show') {
    if (!artifactId) throw new Error('artifact_id is required')
    const artifacts = await listStandaloneArtifacts(projectId, true)
    const artifact = artifacts.find(candidate => candidate.artifact_id === artifactId)
    if (!artifact) throw new Error('Artifact not found')
    return { artifact }
  }
  if (method === 'artifact.delete' || method === 'artifact.remove' || method === 'artifact.restore') {
    const raw = params.artifact_ids || params.artifactIds
    const ids = Array.isArray(raw) ? raw.map(String).filter(id => id.trim()) : []
    if (!ids.length) throw new Error('artifact_ids is required')
    const deleted = method !== 'artifact.restore'
    return await setEmbeddedArtifactsDeleted(projectId, ids, deleted)
  }
  if (method === 'artifact.open') {
    if (!artifactId) throw new Error('artifact_id is required')
    return await openEmbeddedArtifact(projectId, artifactId)
  }
  return null
}

/** `GET /projects/{id}/artifacts/{aid}/file`, the route the viewers call. */
export async function handleStandaloneArtifactHttp(
  request: TransportHttpRequest,
): Promise<TransportHttpResponse | null> {
  const url = new URL(request.path, 'http://localhost')
  const segments = url.pathname.split('/').filter(Boolean)
  if (segments[0] !== 'projects' || segments[2] !== 'artifacts' || segments[4] !== 'file') return null
  if (request.method !== 'GET') return null
  const projectId = decodeURIComponent(segments[1])
  const artifactId = decodeURIComponent(segments[3])
  const bytes = await readEmbeddedArtifactFile(projectId, artifactId)
  if (!bytes) return jsonResponse({ error: 'Artifact not found' }, 404)
  return {
    status: 200,
    headers: { 'Content-Type': bytes.mimeType, 'Content-Length': String(bytes.bytes.length) },
    body: bytes.bytes,
  }
}

/**
 * The snapshot's `artifacts` map: what the message views group under an item.
 *
 * Typed as loose records because that is how the snapshot carries them (the
 * desktop sends dictionaries from its store), and the selectors read fields
 * defensively.
 */
export async function artifactSnapshot(projectId: string): Promise<Record<string, Record<string, unknown>>> {
  const artifacts = await listStandaloneArtifacts(projectId, false)
  return Object.fromEntries(
    artifacts.map(artifact => [artifact.artifact_id, { ...artifact } as Record<string, unknown>]),
  )
}

function jsonResponse(value: unknown, status = 200): TransportHttpResponse {
  return {
    status,
    headers: { 'Content-Type': 'application/json' },
    body: new TextEncoder().encode(JSON.stringify(value)),
  }
}
