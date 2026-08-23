import {
  appServerUrl,
  CoreAppServerClient,
} from '../appServer/client'
import { invoke } from '@tauri-apps/api/core'
import type { CoreAppEvent } from '../appServer/protocol'

export interface PetOverview {
  global_state: 'idle' | 'running' | 'waiting' | 'error'
  running_count: number
  waiting_count: number
  error_count: number
  pending_interactions: PetInteraction[]
  active_errors: Array<Record<string, unknown>>
}

export interface PetInteraction {
  id: string
  thread_id: string
  type: 'approval' | 'ask_user' | string
  title: string
  message: string
  options: string[]
  response_mode: string
}

export interface PetSettings {
  enabled: boolean
  selected_pet: string
  opacity: number
  scale: number
  placement?: { monitor?: string; x?: number | null; y?: number | null }
}

export interface PetPack {
  id: string
  name: string
  valid: boolean
  error: string
  states: Record<string, { fps: number; frames: string[] }>
}

export async function createPetClient(
  onOverview: (overview: PetOverview) => void,
  onConnectionState?: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  clientName = 'lamtools-pet',
) {
  // Tauri creates the Pet WebViews before the shared bootstrap necessarily
  // runs. The Rust side passes the backend address in the child URL, so read
  // that value first and avoid a fragile invoke race in these secondary
  // windows.
  const queryBase = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search).get('api_base') || ''
    : ''
  let rawBase = queryBase || (window as { __LAMTOOLS_API_BASE__?: string }).__LAMTOOLS_API_BASE__ || ''
  // Child WebView profiles can start before the shared bootstrap assignment
  // is visible. Resolve the backend address directly from Tauri so a Pet
  // surface never silently falls back to Vite's frontend port.
  if (!rawBase && (window as any).__TAURI_INTERNALS__) {
    const backendBase = await Promise.race([
      invoke<string>('get_api_base'),
      new Promise<string>((_, reject) => setTimeout(() => reject(new Error('Core address lookup timed out')), 4_000)),
    ])
    rawBase = `${backendBase}/api/core`
  }
  rawBase ||= '/api/core'
  const client = new CoreAppServerClient({
    url: appServerUrl(rawBase, { path: '/api/core/app-server' }),
    clientInfo: { name: clientName, title: clientName === 'lamtools-pet-overlay' ? 'LamTools Pet Overlay' : 'LamTools Pet', version: '0.2.6' },
    onConnectionState,
    onEvent: (event: CoreAppEvent) => {
      if (event.method !== 'pet/overviewChanged') return
      const overview = event.payload?.overview
      if (overview && typeof overview === 'object') onOverview(normalizeOverview(overview))
    },
  })
  return { client, rawBase }
}

export function normalizeOverview(value: unknown): PetOverview {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const state = String(raw.global_state || 'idle')
  return {
    global_state: state === 'waiting' || state === 'error' || state === 'running' ? state : 'idle',
    running_count: numberValue(raw.running_count),
    waiting_count: numberValue(raw.waiting_count),
    error_count: numberValue(raw.error_count),
    pending_interactions: Array.isArray(raw.pending_interactions)
      ? raw.pending_interactions.filter(isInteraction)
      : [],
    active_errors: Array.isArray(raw.active_errors)
      ? raw.active_errors.filter(item => item && typeof item === 'object') as Array<Record<string, unknown>>
      : [],
  }
}

export function defaultPetSettings(value: unknown): PetSettings {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  return {
    enabled: raw.enabled !== false,
    selected_pet: String(raw.selected_pet || 'default-cat'),
    opacity: clamp(numberValue(raw.opacity, 1), 0.2, 1),
    scale: clamp(numberValue(raw.scale, 1), 0.5, 2),
    placement: raw.placement && typeof raw.placement === 'object'
      ? raw.placement as PetSettings['placement']
      : {},
  }
}

function isInteraction(value: unknown): value is PetInteraction {
  if (!value || typeof value !== 'object') return false
  const raw = value as Record<string, unknown>
  return Boolean(raw.id && raw.thread_id)
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value))
}
