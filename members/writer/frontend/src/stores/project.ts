import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '@/api'
import type { Project, ProjectCreate, ProjectUpdate, Session } from '@/types'

export const useProjectStore = defineStore('project', () => {
  const projects = ref<Project[]>([])
  const activeProject = ref<Project | null>(null)
  const loading = ref(false)
  const agentsMdContent = ref('')
  const agentsMdExists = ref(false)

  const activeProjectId = computed(() => activeProject.value?.id ?? null)

  async function fetchProjects() {
    loading.value = true
    try {
      projects.value = await api.listProjects()
    } finally {
      loading.value = false
    }
  }

  async function createProject(data: ProjectCreate): Promise<{ project: Project; session: Session }> {
    const result = await api.createProject(data)
    projects.value.push(result.project)
    return result
  }

  async function createProjectSession(projectId: string, title = 'New Session'): Promise<Session> {
    return api.createProjectSession(projectId, title)
  }

  function selectProject(project: Project | null) {
    activeProject.value = project
  }

  async function updateProject(id: string, data: ProjectUpdate): Promise<Project> {
    const p = await api.updateProject(id, data)
    const idx = projects.value.findIndex(x => x.id === id)
    if (idx >= 0) projects.value[idx] = p
    if (activeProject.value?.id === id) activeProject.value = p
    return p
  }

  async function deleteProject(id: string) {
    await api.deleteProject(id)
    projects.value = projects.value.filter(x => x.id !== id)
    if (activeProject.value?.id === id) activeProject.value = null
  }

  async function fetchAgentsMd(projectId: string) {
    return api.getAgentsMd(projectId)
  }

  async function saveAgentsMd(projectId: string, content: string) {
    return api.updateAgentsMd(projectId, content)
  }

  return {
    projects, activeProject, loading, agentsMdContent, agentsMdExists, activeProjectId,
    fetchProjects, createProject, createProjectSession, selectProject, updateProject, deleteProject,
    fetchAgentsMd, saveAgentsMd,
  }
})
