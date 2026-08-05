import {
  createSessionMapper,
  type CoreSessionRawLike,
} from '@lamtools/ui'

const sessionMapper = createSessionMapper('sage-sessions')
const API_BASE = import.meta.env.VITE_API_BASE || ''

class SageApiError extends Error {
  constructor(public readonly status: number, public readonly body: unknown) {
    super(`Sage API ${status}: ${typeof body === 'string' ? body : JSON.stringify(body)}`)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) {
    const text = await response.text()
    let body: unknown = text
    try { body = JSON.parse(text) } catch { /* keep server text */ }
    throw new SageApiError(response.status, body)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function jsonRequest(method: string, body: Record<string, unknown>): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

function newId(prefix: string): string {
  const suffix = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${suffix}`
}

export async function listCoreSessions() {
  const raw = await request<CoreSessionRawLike[]>('/api/core/sessions')
  return raw.map(sessionMapper.toCore)
}

export async function createCoreSession(title = '新的研究') {
  const raw = await request<CoreSessionRawLike>('/api/core/sessions', jsonRequest('POST', {
    id: newId('sage'),
    member_id: 'sage',
    title,
    status: 'idle',
    metadata: {},
  }))
  return sessionMapper.toCore(raw)
}

export { SageApiError }
