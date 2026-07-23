export interface CoreGoal {
  id: string
  thread_id: string
  objective: string
  status: 'active' | 'blocked' | 'archived'
  status_reason?: string
  completion_criteria?: string[]
  metadata?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CoreArrangeJob {
  id: string
  thread_id: string
  source_thread_id: string
  project_id: string
  work_root?: string
  kind: 'focus' | 'routine'
  operation: string
  payload: Record<string, unknown>
  trigger: Record<string, unknown>
  title: string
  session_strategy: 'fixed' | 'new'
  model_id?: string
  observer?: Record<string, unknown>
  status: 'scheduled' | 'waiting' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
  next_run_at?: string | null
  run_count: number
  max_runs?: number | null
  occurrence_id?: string
  signal?: Record<string, unknown>
  lease_owner?: string
  lease_expires_at?: string | null
  last_error?: string
  revision: number
  created_at: string
  updated_at: string
}