import { ref, type Ref } from 'vue'
import { listGoals, updateGoal } from '../durable/api'
import type { CoreGoal } from '../durable/types'

export interface UseCoreGoalsOptions {
  activeSessionId: Ref<string | null>
}

export function useCoreGoals(options: UseCoreGoalsOptions) {
  const { activeSessionId } = options
  const activeGoal = ref<CoreGoal | null>(null)
  const goalError = ref('')
  let goalRequestGeneration = 0

  async function refreshGoal(threadId?: string | null) {
    const tid = threadId ?? activeSessionId.value
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
