import {
  appServerUrl,
  CoreAppServerClient,
} from '../appServer'
import type { CoreGoal, CoreArrangeJob } from './types'

async function appServerOperation<T>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  const client = new CoreAppServerClient({
    url: appServerUrl('', { path: '/api/core/app-server' }),
    clientInfo: { name: 'core_ui', title: 'Core', version: '0.1.0' },
  })
  try {
    await client.connect()
    return await client.request(method, params) as T
  } finally {
    client.close()
  }
}

export function listGoals(threadId?: string): Promise<CoreGoal[]> {
  const params: Record<string, unknown> = {}
  if (threadId) params.thread_id = threadId
  return appServerOperation<{ goals?: CoreGoal[] }>('goal.list', params)
    .then(result => result.goals ?? [])
}

export function updateGoal(goalId: string, status: string, reason?: string): Promise<CoreGoal> {
  const params: Record<string, unknown> = { goal_id: goalId, status }
  if (reason) params.status_reason = reason
  return appServerOperation<{ goal?: CoreGoal }>('goal.update', params)
    .then((result) => {
      if (!result.goal) throw new Error('goal.update response is missing goal')
      return result.goal
    })
}

export function createGoal(threadId: string, objective: string): Promise<CoreGoal> {
  return appServerOperation<{ goal?: CoreGoal }>('goal.create', {
    thread_id: threadId,
    objective,
  })
    .then((result) => {
      if (!result.goal) throw new Error('goal.create response is missing goal')
      return result.goal
    })
}

export function listArrangeJobs(workRoot?: string): Promise<CoreArrangeJob[]> {
  const params: Record<string, unknown> = {}
  if (workRoot) params.work_root = workRoot
  return appServerOperation<{ jobs?: CoreArrangeJob[] }>('arrange.list', params)
    .then(result => result.jobs ?? [])
}

export function createArrangeJob(params: {
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
}): Promise<CoreArrangeJob> {
  return appServerOperation<{ job?: CoreArrangeJob }>('arrange.create', params)
    .then((result) => {
      if (!result.job) throw new Error('arrange.create response is missing job')
      return result.job
    })
}

export function updateArrangeJob(
  jobId: string,
  action: 'pause' | 'resume' | 'cancel',
): Promise<CoreArrangeJob> {
  return appServerOperation<{ job?: CoreArrangeJob }>(`arrange.${action}`, { job_id: jobId })
    .then((result) => {
      if (!result.job) throw new Error(`arrange.${action} response is missing job`)
      return result.job
    })
}

export function renameArrangeJob(jobId: string, title: string): Promise<CoreArrangeJob> {
  return appServerOperation<{ job?: CoreArrangeJob }>('arrange.update', { job_id: jobId, title })
    .then((result) => {
      if (!result.job) throw new Error('arrange.update response is missing job')
      return result.job
    })
}

export function editArrangeJob(
  jobId: string,
  fields: { instruction?: string; trigger?: Record<string, unknown>; session_strategy?: 'fixed' | 'new'; model_id?: string },
): Promise<CoreArrangeJob> {
  return appServerOperation<{ job?: CoreArrangeJob }>('arrange.update', { job_id: jobId, ...fields })
    .then((result) => {
      if (!result.job) throw new Error('arrange.update response is missing job')
      return result.job
    })
}

export function listArrangeOccurrences(jobId: string): Promise<Array<{
  id: string; job_id: string; status: string; scheduled_at: string;
  started_at?: string | null; completed_at?: string | null;
  attempt_count: number; last_error?: string;
}>> {
  return appServerOperation<{ occurrences?: Array<Record<string, unknown>> }>('arrange.occurrence.list', { job_id: jobId })
    .then(result => (result.occurrences ?? []) as Array<{
      id: string; job_id: string; status: string; scheduled_at: string;
      started_at?: string | null; completed_at?: string | null;
      attempt_count: number; last_error?: string;
    }>)
}
