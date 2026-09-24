import {
  createEmbeddedGoal,
  hasEmbeddedRustCore,
  listEmbeddedGoals,
  readEmbeddedGoal,
  updateEmbeddedGoal,
} from '../native/rustAgent'

/**
 * Durable goals for the standalone transport.
 *
 * The desktop keeps goals in `runtime/goal.py`; the phone keeps the same model
 * and status machine in the host's `goals.db`. The RPC names, payload shapes and
 * refusal wording match, so the shared Goals panel behaves identically.
 *
 * Threads live in the session metadata on this platform, and the desktop's
 * accept both `thread_id` and `threadId`, so both are read here.
 */
export async function goalRpc(
  method: string,
  params: Record<string, unknown>,
): Promise<Record<string, unknown> | null> {
  if (!method.startsWith('goal.')) return null
  if (!hasEmbeddedRustCore()) throw new Error(`移动端独立模式不支持 ${method}`)
  const goalId = String(params.goal_id || params.goalId || params.id || '')
  if (method === 'goal.create') {
    const threadId = String(params.thread_id || params.threadId || '').trim()
    const objective = String(params.objective || '')
    const criteria = params.completion_criteria ?? params.completionCriteria
    return await createEmbeddedGoal({
      threadId,
      objective,
      completionCriteria: Array.isArray(criteria) ? criteria.map(String) : [],
      metadata: isRecord(params.metadata) ? params.metadata : {},
      goalId: goalId || undefined,
    })
  }
  if (method === 'goal.get') {
    if (!goalId) throw new Error('goal_id is required')
    return await readEmbeddedGoal(goalId)
  }
  if (method === 'goal.list') {
    return await listEmbeddedGoals(
      String(params.thread_id || params.threadId || '') || undefined,
      String(params.status || '') || undefined,
    )
  }
  if (method === 'goal.update') {
    if (!goalId) throw new Error('goal_id is required')
    const criteria = params.completion_criteria ?? params.completionCriteria
    // A field the caller did not send must stay untouched: the panel clears a
    // status reason with `""` without touching the objective.
    return await updateEmbeddedGoal({
      goalId,
      ...(Object.hasOwn(params, 'objective') ? { objective: String(params.objective || '') } : {}),
      ...(criteria !== undefined ? { completionCriteria: Array.isArray(criteria) ? criteria.map(String) : [] } : {}),
      ...(Object.hasOwn(params, 'status') ? { status: String(params.status || '') } : {}),
      ...(Object.hasOwn(params, 'status_reason') || Object.hasOwn(params, 'statusReason')
        ? { statusReason: String(params.status_reason ?? params.statusReason ?? '') }
        : {}),
      ...(Object.hasOwn(params, 'metadata') && isRecord(params.metadata) ? { metadata: params.metadata } : {}),
    })
  }
  return null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
