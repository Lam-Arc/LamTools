import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '@/api'
import { removeSessionsByIds } from '@/lib/session-list'
import type { Session, SessionCreate, SessionUpdate } from '@/types'

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<Session[]>([])
  const activeSession = ref<Session | null>(null)
  const loading = ref(false)

  const activeSessionId = computed(() => activeSession.value?.id ?? null)

  const sessionsByProject = computed(() => {
    const map = new Map<string, Session[]>()
    for (const s of sessions.value) {
      const pid = s.project_id ?? '__none__'
      if (!map.has(pid)) map.set(pid, [])
      map.get(pid)!.push(s)
    }
    return map
  })

  async function fetchSessions(projectId?: string) {
    loading.value = true
    try {
      if (projectId) {
        sessions.value = await api.listProjectSessions(projectId)
      } else {
        sessions.value = await api.listSessions()
      }
    } finally {
      loading.value = false
    }
  }

  async function createSession(data: SessionCreate): Promise<Session> {
    const s = await api.createSession(data)
    sessions.value.unshift(s)
    return s
  }

  function selectSession(session: Session | null) {
    activeSession.value = session
  }

  async function updateSession(id: string, data: SessionUpdate): Promise<Session> {
    const s = await api.updateSession(id, data)
    const idx = sessions.value.findIndex(x => x.id === id)
    if (idx >= 0) sessions.value[idx] = s
    if (activeSession.value?.id === id) activeSession.value = s
    return s
  }

  async function deleteSession(id: string) {
    await api.deleteSession(id)
    removeSessions([id])
  }

  function removeSessions(ids: Iterable<string>) {
    const deleted = new Set(ids)
    sessions.value = removeSessionsByIds(sessions.value, deleted)
    if (activeSession.value?.id && deleted.has(activeSession.value.id)) {
      activeSession.value = null
    }
  }

  function clearMessages() {
    // Legacy no-op: Writer messages are rendered from app-server snapshots.
  }

  function updateSessionField(id: string, patch: Partial<Session>) {
    const idx = sessions.value.findIndex(x => x.id === id)
    if (idx >= 0) {
      sessions.value[idx] = { ...sessions.value[idx], ...patch }
    }
    if (activeSession.value?.id === id) {
      activeSession.value = { ...activeSession.value, ...patch }
    }
  }

  return {
    sessions, activeSession, loading, activeSessionId, sessionsByProject,
    fetchSessions, createSession, selectSession, updateSession, deleteSession,
    clearMessages, updateSessionField, removeSessions,
  }
})
