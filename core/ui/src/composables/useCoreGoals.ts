import { ref, type Ref } from 'vue'
import { listGoals, updateGoal } from '../durable/api'
import type { CoreGoal } from '../durable/types'

/** Max goal refresh frequency during a stream (stream-tick watchers fire far more often). */
const GOAL_REFRESH_THROTTLE_MS = 2_000

export interface UseCoreGoalsOptions {
  activeSessionId: Ref<string | null>
}

export function useCoreGoals(options: UseCoreGoalsOptions) {
  const { activeSessionId } = options
  const activeGoal = ref<CoreGoal | null>(null)
  const goalError = ref('')
  let goalRequestGeneration = 0
  let throttledUntil = 0

  async function refreshGoal(threadId?: string | null, force = false) {
    const tid = threadId ?? activeSessionId.value
    // Throttle the per-stream-tick refresh: goal strip still updates at most
    // every GOAL_REFRESH_THROTTLE_MS during a long stream, while force
    // (turn finished / session switch) refreshes immediately.
    const now = Date.now()
    if (!force && now < throttledUntil) return
    throttledUntil = now + GOAL_REFRESH_THROTTLE_MS
    const generation = ++goalRequestGeneration
    goalError.value = ''
    if (!tid) return
    try {
      const goals = await listGoals(tid)
      if (generation !== goalRequestGeneration || activeSessionId.value !== tid) return
      activeGoal.value = goals.find(goal => ['active', 'blocked'].includes(goal.status)) ?? null
    } catch (error) {
      if (generation !== goalRequestGeneration || activeSessionId.value !== tid) return
      goalError.value = error instanceof Error ? error.message : '目标读取失败'
    }
  }

  async function handleCancelGoal(goal: CoreGoal) {
    try {
      await updateGoal(goal.id, 'archived', 'cancelled by user')
      if (activeGoal.value?.id === goal.id) activeGoal.value = null
    } catch (error) {
      goalError.value = error instanceof Error ? error.message : '目标取消失败'
    }
  }

  return { activeGoal, goalError, refreshGoal, handleCancelGoal }
}
