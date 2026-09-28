import {
  deleteEmbeddedPlan,
  hasEmbeddedRustCore,
  listEmbeddedPlans,
  readEmbeddedPlan,
  readEmbeddedPlanRevisions,
  restoreEmbeddedPlan,
  revertEmbeddedPlan,
  saveEmbeddedPlan,
} from '../native/rustAgent'

/**
 * Plan packages (方案) for the standalone transport.
 *
 * The desktop answers these names from `app/plan_operations.py` over its own
 * SQLite tables; the phone answers them from the host's `plans.db`. Payload
 * shapes, camelCase fallbacks and refusal wording match, so the shared plan
 * library behaves identically on both hosts — and the rules themselves live in
 * one shared fixture set (`core/protocol/plan-package-v1-fixtures.json`) that
 * both hosts' tests run.
 */
export async function planRpc(
  method: string,
  params: Record<string, unknown>,
): Promise<Record<string, unknown> | null> {
  if (!method.startsWith('plan.')) return null
  if (!hasEmbeddedRustCore()) throw new Error(`移动端独立模式不支持 ${method}`)
  const planId = planIdOf(params)

  if (method === 'plan.save') {
    // The payload is the package itself. The host accepts both spellings of the
    // envelope fields, and this bridge settles on one so everything downstream
    // sees a single shape.
    const payload = { ...params }
    const expected = payload.expected_revision ?? payload.expectedRevision
    if (expected !== undefined && expected !== null && expected !== '') {
      payload.expected_revision = Number(expected)
    } else {
      delete payload.expected_revision
    }
    delete payload.expectedRevision
    if (payload.planId !== undefined && payload.plan_id === undefined) payload.plan_id = payload.planId
    delete payload.planId
    if (payload.projectId !== undefined && payload.project_id === undefined) {
      payload.project_id = payload.projectId
    }
    delete payload.projectId
    if (payload.id !== undefined && payload.plan_id === undefined) payload.plan_id = payload.id
    delete payload.id
    return await saveEmbeddedPlan(payload)
  }
  if (method === 'plan.get') {
    if (!planId) throw new Error('plan_id is required')
    return await readEmbeddedPlan(planId)
  }
  if (method === 'plan.list') {
    return await listEmbeddedPlans({
      projectId: String(params.project_id || params.projectId || ''),
      status: String(params.status || ''),
      includeDeleted: Boolean(params.include_deleted || params.includeDeleted),
    })
  }
  if (method === 'plan.delete') {
    if (!planId) throw new Error('plan_id is required')
    return await deleteEmbeddedPlan(planId)
  }
  if (method === 'plan.restore') {
    if (!planId) throw new Error('plan_id is required')
    return await restoreEmbeddedPlan(planId)
  }
  if (method === 'plan.revert') {
    if (!planId) throw new Error('plan_id is required')
    const revision = Number(params.revision ?? params.to_revision ?? params.toRevision ?? 0)
    if (!Number.isFinite(revision) || revision <= 0) throw new Error('plan revision must be a number')
    return await revertEmbeddedPlan(planId, Math.trunc(revision))
  }
  if (method === 'plan.revisions') {
    if (!planId) throw new Error('plan_id is required')
    return await readEmbeddedPlanRevisions(planId)
  }
  return null
}

function planIdOf(params: Record<string, unknown>): string {
  return String(params.plan_id || params.planId || params.id || '').trim()
}
