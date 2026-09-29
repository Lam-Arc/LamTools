/**
 * Plan-library orchestration: one place that talks to `plan.*` over RPC and
 * keeps the list, the edited draft, the version history and the conflict state
 * consistent. The panel stays a view over this; the tests drive it directly.
 */

import { computed, reactive, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import {
  addQuestion,
  addStep,
  buildPlanPatch,
  clonePlan,
  emptyPlan,
  extractPlan,
  extractPlans,
  extractRevisions,
  isPlanStatus,
  isRevisionConflict,
  normalizePlan,
  planErrorMessage,
  validatePlanDraft,
} from './planEditing'
import type { PlanPackage, PlanRevisionSummary, PlanStatus } from './types'

export type PlanLibraryRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

export interface PlanProjectOption {
  id: string
  name: string
}

export interface UsePlanLibraryOptions {
  requestRpc?: PlanLibraryRpc
  projectId?: MaybeRefOrGetter<string | null>
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

export function usePlanLibrary(options: UsePlanLibraryOptions) {
  const requestRpc = options.requestRpc

  const plans = ref<PlanPackage[]>([])
  const projects = ref<PlanProjectOption[]>([])
  const loading = ref(false)
  const error = ref('')
  const conflictNotice = ref('')
  const statusFilter = ref<'' | PlanStatus>('')
  const projectFilter = ref<string>(toValue(options.projectId) || '')
  const includeDeleted = ref(false)
  const selectedId = ref('')
  const hasDraft = ref(false)
  // A reactive object, not a ref: the editor binds `v-model="draft.title"` on it
  // directly, and replacing it wholesale would break those bindings.
  const draft = reactive<PlanPackage>(emptyPlan(''))
  const savedSnapshot = ref<PlanPackage | null>(null)
  const revisions = ref<PlanRevisionSummary[]>([])
  const revisionsLoading = ref(false)
  const saving = ref(false)
  const busyId = ref('')
  let listRevision = 0
  let revisionsRevision = 0

  const isNew = computed(() => hasDraft.value && !savedSnapshot.value?.plan_id)
  const scopeProjectId = computed(() => projectFilter.value || toValue(options.projectId) || '')
  const dirty = computed(() => {
    if (!hasDraft.value) return false
    if (isNew.value) return true
    const patch = buildPlanPatch(savedSnapshot.value, draft)
    return Object.keys(patch).some((key) => !['plan_id', 'project_id', 'expected_revision'].includes(key))
  })
  const openQuestionTotal = computed(() => plans.value.reduce(
    (total, plan) => total + plan.open_questions.filter((question) => question.status === 'open').length,
    0,
  ))

  async function refresh(): Promise<void> {
    const revision = ++listRevision
    loading.value = true
    error.value = ''
    if (!requestRpc) {
      plans.value = []
      loading.value = false
      return
    }
    try {
      const params: Record<string, unknown> = { include_deleted: includeDeleted.value }
      if (projectFilter.value) params.project_id = projectFilter.value
      if (statusFilter.value) params.status = statusFilter.value
      const result = await requestRpc('plan.list', params)
      if (revision !== listRevision) return
      plans.value = extractPlans(result)
    } catch (cause) {
      if (revision === listRevision) error.value = planErrorMessage(cause)
    } finally {
      if (revision === listRevision) loading.value = false
    }
  }

  function applyDraft(next: PlanPackage): void {
    Object.assign(draft, clonePlan(next))
  }

  async function loadProjects(): Promise<void> {
    if (!requestRpc) return
    try {
      const result = await requestRpc('project.list', {})
      const rows = asRecord(result).projects
      projects.value = Array.isArray(rows)
        ? rows.flatMap((value) => {
          const row = asRecord(value)
          const id = str(row.id)
          return id ? [{ id, name: str(row.name) || id }] : []
        })
        : []
    } catch {
      // A host that cannot list projects still works: the scope select falls
      // back to the project the shell already knows.
      projects.value = []
    }
  }

  async function loadRevisions(planId: string): Promise<void> {
    const revision = ++revisionsRevision
    if (!planId || !requestRpc) {
      revisions.value = []
      return
    }
    revisionsLoading.value = true
    try {
      const result = await requestRpc('plan.revisions', { plan_id: planId })
      if (revision === revisionsRevision) revisions.value = extractRevisions(result)
    } catch {
      if (revision === revisionsRevision) revisions.value = []
    } finally {
      if (revision === revisionsRevision) revisionsLoading.value = false
    }
  }

  function selectPlan(plan: PlanPackage | unknown): void {
    const normalized = normalizePlan(plan)
    if (!normalized) return
    selectedId.value = normalized.plan_id
    savedSnapshot.value = clonePlan(normalized)
    applyDraft(normalized)
    hasDraft.value = true
    conflictNotice.value = ''
    error.value = ''
    void loadRevisions(normalized.plan_id)
  }

  function startNew(): void {
    const projectId = scopeProjectId.value
    selectedId.value = ''
    savedSnapshot.value = null
    applyDraft(emptyPlan(projectId))
    hasDraft.value = true
    revisions.value = []
    conflictNotice.value = ''
    error.value = ''
  }

  function closeDraft(): void {
    selectedId.value = ''
    savedSnapshot.value = null
    hasDraft.value = false
    applyDraft(emptyPlan(''))
    revisions.value = []
    conflictNotice.value = ''
    error.value = ''
  }

  /** Drop local edits and re-edit the stored revision. */
  function resetDraft(): void {
    if (!savedSnapshot.value) {
      startNew()
      return
    }
    applyDraft(savedSnapshot.value)
    conflictNotice.value = ''
    error.value = ''
  }

  async function reloadSelected(): Promise<void> {
    const planId = selectedId.value || savedSnapshot.value?.plan_id || ''
    if (!planId || !requestRpc) return
    try {
      const result = await requestRpc('plan.get', { plan_id: planId })
      const fresh = extractPlan(result)
      if (!fresh) throw new Error(`Plan not found: ${planId}`)
      selectedId.value = fresh.plan_id
      savedSnapshot.value = clonePlan(fresh)
      applyDraft(fresh)
      hasDraft.value = true
      await Promise.all([refresh(), loadRevisions(fresh.plan_id)])
    } catch (cause) {
      error.value = planErrorMessage(cause)
      closeDraft()
    }
  }

  async function save(): Promise<boolean> {
    if (!hasDraft.value || !requestRpc) return false
    const invalid = validatePlanDraft(draft)
    if (invalid) {
      error.value = invalid
      return false
    }
    const original = savedSnapshot.value
    const patch = buildPlanPatch(original, draft)
    saving.value = true
    error.value = ''
    conflictNotice.value = ''
    try {
      const result = await requestRpc('plan.save', patch as Record<string, unknown>)
      const saved = extractPlan(result)
      if (!saved) throw new Error('保存后未返回方案')
      selectedId.value = saved.plan_id
      savedSnapshot.value = clonePlan(saved)
      applyDraft(saved)
      hasDraft.value = true
      await Promise.all([refresh(), loadRevisions(saved.plan_id)])
      return true
    } catch (cause) {
      if (isRevisionConflict(cause) && original?.plan_id) {
        // Never overwrite the other writer: say so and show them the latest.
        conflictNotice.value = '这份方案已被其他端改过，你的改动没有保存；已为你重新载入最新版本。'
        await reloadSelected()
      } else {
        error.value = planErrorMessage(cause)
      }
      return false
    } finally {
      saving.value = false
    }
  }

  async function remove(planId: string): Promise<void> {
    if (!planId || !requestRpc) return
    busyId.value = planId
    error.value = ''
    try {
      await requestRpc('plan.delete', { plan_id: planId })
      if (selectedId.value === planId) closeDraft()
      await refresh()
    } catch (cause) {
      error.value = planErrorMessage(cause)
    } finally {
      busyId.value = ''
    }
  }

  async function restore(planId: string): Promise<void> {
    if (!planId || !requestRpc) return
    busyId.value = planId
    error.value = ''
    try {
      await requestRpc('plan.restore', { plan_id: planId })
      await refresh()
    } catch (cause) {
      error.value = planErrorMessage(cause)
    } finally {
      busyId.value = ''
    }
  }

  async function revert(revision: number): Promise<boolean> {
    const planId = selectedId.value || savedSnapshot.value?.plan_id || ''
    if (!planId || !requestRpc || !Number.isFinite(revision) || revision <= 0) return false
    saving.value = true
    error.value = ''
    conflictNotice.value = ''
    try {
      const result = await requestRpc('plan.revert', { plan_id: planId, revision })
      const reverted = extractPlan(result)
      if (!reverted) throw new Error('回滚后未返回方案')
      selectedId.value = reverted.plan_id
      savedSnapshot.value = clonePlan(reverted)
      applyDraft(reverted)
      hasDraft.value = true
      await Promise.all([refresh(), loadRevisions(reverted.plan_id)])
      return true
    } catch (cause) {
      error.value = planErrorMessage(cause)
      return false
    } finally {
      saving.value = false
    }
  }

  function setStatusFilter(value: string): void {
    statusFilter.value = isPlanStatus(value) ? value : ''
    void refresh()
  }

  function setProjectFilter(value: string): void {
    projectFilter.value = value || ''
    void refresh()
  }

  function toggleDeleted(): void {
    includeDeleted.value = !includeDeleted.value
    void refresh()
  }

  function addDraftStep(): void {
    if (hasDraft.value) addStep(draft)
  }

  function removeDraftStep(index: number): void {
    if (hasDraft.value) draft.checklist.steps.splice(index, 1)
  }

  function addDraftQuestion(): void {
    if (hasDraft.value) addQuestion(draft)
  }

  function removeDraftQuestion(index: number): void {
    if (hasDraft.value) draft.open_questions.splice(index, 1)
  }

  watch(() => toValue(options.projectId), (projectId) => {
    const next = projectId || ''
    if (next === projectFilter.value) return
    projectFilter.value = next
    void refresh()
  })

  return {
    // state
    plans,
    projects,
    loading,
    error,
    conflictNotice,
    statusFilter,
    projectFilter,
    includeDeleted,
    selectedId,
    hasDraft,
    draft,
    savedSnapshot,
    revisions,
    revisionsLoading,
    saving,
    busyId,
    // derived
    isNew,
    dirty,
    openQuestionTotal,
    scopeProjectId,
    // actions
    refresh,
    loadProjects,
    loadRevisions,
    selectPlan,
    startNew,
    closeDraft,
    resetDraft,
    reloadSelected,
    save,
    remove,
    restore,
    revert,
    setStatusFilter,
    setProjectFilter,
    toggleDeleted,
    addDraftStep,
    removeDraftStep,
    addDraftQuestion,
    removeDraftQuestion,
  }
}
