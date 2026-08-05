// ============================================================
// LamWriter Core API Module -- typed wrappers for /api/core
// These endpoints were added in the backend Phase 7 migration.
// Vite dev proxy handles /api -> backend.
// ============================================================

import type { CoreSessionListItem } from '@lamtools/ui'
import {
  createSessionMapper,
  type CoreSessionRawLike,
} from '@lamtools/ui'

// Re-use API_BASE from the main API module for desktop/electron support.
import { API_BASE } from '@/api'

// --- Core mapper instances (Writer-specific groupId) ---

const sessionMapper = createSessionMapper('writer-sessions')

// --- Raw types not covered by Core helpers ---

interface CoreProviderRaw {
  id: string
  kind: string
  name: string
  base_url: string
  api_key_ref: string
  default_model: string
  models: string[]
  metadata?: Record<string, unknown>
  enabled: boolean
}

// --- Generic fetch helper (shared API_BASE pattern) ---

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers as Record<string, string> | undefined) },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Core API ${res.status}: ${text}`)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return res.json()
}

// --- Core session endpoints ---
// GET /api/core/sessions
// POST /api/core/sessions
// GET /api/core/sessions/{id}

export async function listCoreSessions(): Promise<CoreSessionListItem[]> {
  const raw = await request<CoreSessionRawLike[]>('/api/core/sessions')
  return raw.map(sessionMapper.toCore)
}

export async function createCoreSession(
  title: string = 'New Session',
  workRoot: string = '',
): Promise<CoreSessionListItem> {
  const body: Record<string, unknown> = { title }
  if (workRoot) body.work_root = workRoot
  const raw = await request<CoreSessionRawLike>('/api/core/sessions', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return sessionMapper.toCore(raw)
}

// --- Core provider endpoint ---
// GET /api/core/providers

export async function listCoreProviders(): Promise<CoreProviderRaw[]> {
  return request<CoreProviderRaw[]>('/api/core/providers')
}
