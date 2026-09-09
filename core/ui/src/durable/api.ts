import type { CoreGoal, CoreArrangeJob } from './types'

export type CoreDurableRequest = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

export interface CoreArrangeOccurrence {
  id: string
  job_id: string
  status: string
  scheduled_at: string
  started_at?: string | null
  completed_at?: string | null
  attempt_count: number
  last_error?: string
}

export interface CoreDurableApi {
  listGoals(threadId?: string): Promise<CoreGoal[]>
  updateGoal(goalId: string, status: string, reason?: string): Promise<CoreGoal>
  createGoal(threadId: string, objective: string): Promise<CoreGoal>
  listArrangeJobs(workRoot?: string): Promise<CoreArrangeJob[]>
  createArrangeJob(params: {
    thread_id: string
    work_root: string
    kind: string
    operation: string
    payload: { message: string }
    trigger: Record<string, unknown>
    title?: string
    session_strategy?: string
    model_id?: string
    max_runs?: number
  }): Promise<CoreArrangeJob>
  updateArrangeJob(jobId: string, action: 'pause' | 'resume' | 'cancel'): Promise<CoreArrangeJob>
  renameArrangeJob(jobId: string, title: string): Promise<CoreArrangeJob>
  editArrangeJob(jobId: string, fields: {
    instruction?: string
    trigger?: Record<string, unknown>
    session_strategy?: 'fixed' | 'new'
    model_id?: string
  }): Promise<CoreArrangeJob>
  listArrangeOccurrences(jobId: string): Promise<CoreArrangeOccurrence[]>
}

/** Durable operations are transport-neutral; the host supplies Core RPC. */
export function createDurableApi(request: CoreDurableRequest): CoreDurableApi {
  async function operation<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return await request(method, params) as T
  }

  return {
    listGoals(threadId) {
      return operation<{ goals?: CoreGoal[] }>('goal.list', threadId ? { thread_id: threadId } : {})
        .then(result => result.goals ?? [])
    },
    updateGoal(goalId, status, reason) {
      return operation<{ goal?: CoreGoal }>('goal.update', {
        goal_id: goalId,
        status,
        ...(reason ? { status_reason: reason } : {}),
      }).then((result) => {
        if (!result.goal) throw new Error('goal.update response is missing goal')
        return result.goal
      })
    },
    createGoal(threadId, objective) {
      return operation<{ goal?: CoreGoal }>('goal.create', {
        thread_id: threadId,
        objective,
      }).then((result) => {
        if (!result.goal) throw new Error('goal.create response is missing goal')
        return result.goal
      })
    },
    listArrangeJobs(workRoot) {
      return operation<{ jobs?: CoreArrangeJob[] }>('arrange.list', workRoot ? { work_root: workRoot } : {})
        .then(result => result.jobs ?? [])
    },
    createArrangeJob(params) {
      return operation<{ job?: CoreArrangeJob }>('arrange.create', params)
        .then((result) => {
          if (!result.job) throw new Error('arrange.create response is missing job')
          return result.job
        })
    },
    updateArrangeJob(jobId, action) {
      return operation<{ job?: CoreArrangeJob }>(`arrange.${action}`, { job_id: jobId })
        .then((result) => {
          if (!result.job) throw new Error(`arrange.${action} response is missing job`)
          return result.job
        })
    },
    renameArrangeJob(jobId, title) {
      return operation<{ job?: CoreArrangeJob }>('arrange.update', { job_id: jobId, title })
        .then((result) => {
          if (!result.job) throw new Error('arrange.update response is missing job')
          return result.job
        })
    },
    editArrangeJob(jobId, fields) {
      return operation<{ job?: CoreArrangeJob }>('arrange.update', { job_id: jobId, ...fields })
        .then((result) => {
          if (!result.job) throw new Error('arrange.update response is missing job')
          return result.job
        })
    },
    listArrangeOccurrences(jobId) {
      return operation<{ occurrences?: CoreArrangeOccurrence[] }>('arrange.occurrence.list', { job_id: jobId })
        .then(result => result.occurrences ?? [])
    },
  }
}
