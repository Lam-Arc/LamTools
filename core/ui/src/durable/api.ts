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

export function listArrangeJobs(): Promise<CoreArrangeJob[]> {
  return appServerOperation<{ jobs?: CoreArrangeJob[] }>('arrange.list')
    .then(result => result.jobs ?? [])
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
