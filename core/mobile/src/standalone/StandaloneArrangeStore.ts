import type { LocalRepository } from '../storage'
import { createStandaloneStateStorage, type StandaloneStateStorage } from './StandaloneStateStorage'

interface Job extends Record<string, unknown> {
  id: string
  thread_id: string
  source_thread_id: string
  project_id: string
  work_root: string
  kind: string
  operation: string
  payload: Record<string, unknown>
  trigger: Record<string, unknown>
  title: string
  session_strategy: string
  status: string
  next_run_at: string | null
  run_count: number
  max_runs: number | null
  revision: number
  created_at: string
  updated_at: string
  last_error: string
}

interface State { jobs: Job[]; occurrences: Record<string, Record<string, unknown>[]> }
export const STANDALONE_ARRANGE_NOTICE = '本机独立模式尚无 Android 后台调度器。安排会保存为暂停草稿，不会自动执行。'

export class StandaloneArrangeStore {
  private state: State | null = null

  constructor(
    private readonly repository: LocalRepository,
    private readonly storage: StandaloneStateStorage<State> = createStandaloneStateStorage({
      database: 'lamtools-mobile-arrange', scope: 'arrange', legacyKey: 'lamtools.mobile.standalone.arrange.v1',
    }),
  ) {}

  async handleRpc(method: string, params: Record<string, unknown>): Promise<Record<string, unknown> | null> {
    if (!method.startsWith('arrange.')) return null
    const state = await this.load()
    const id = String(params.job_id || '')
    const job = state.jobs.find(value => value.id === id)
    if (method === 'arrange.list') {
      const workRoot = String(params.work_root || '')
      return { jobs: state.jobs.filter(value => !workRoot || value.work_root === workRoot), scheduler_available: false, scheduler_notice: STANDALONE_ARRANGE_NOTICE }
    }
    if (method === 'arrange.create') {
      const payload = record(params.payload)
      const trigger = record(params.trigger)
      if (String(params.operation || '') !== 'turn.start' || !String(payload.message || '').trim()) throw new Error('安排指令无效')
      if (!['once', 'interval', 'calendar', 'event'].includes(String(trigger.type || ''))) throw new Error('安排触发方式无效')
      const project = (await this.repository.listProjects()).find(value => value.workRoot === params.work_root || value.path === params.work_root)
      if (!project) throw new Error('项目不存在；请选择本机项目')
      const threadId = String(params.thread_id || '')
      if (threadId && !(await this.repository.listSessions()).some(value => value.id === threadId && value.metadata?.project_id === project.id)) {
        throw new Error('固定会话与项目不匹配')
      }
      const now = new Date().toISOString()
      const created: Job = {
        id: globalThis.crypto?.randomUUID?.() || `arrange-${Date.now()}`,
        thread_id: threadId, source_thread_id: threadId, project_id: project.id,
        work_root: project.workRoot || project.path, kind: String(params.kind || 'routine'),
        operation: 'turn.start', payload: { message: String(payload.message).trim() },
        trigger, title: String(params.title || ''),
        session_strategy: String(params.session_strategy || 'new'),
        ...(params.model_id ? { model_id: String(params.model_id) } : {}),
        status: 'paused', next_run_at: null, run_count: 0,
        max_runs: positiveNumber(params.max_runs), revision: 1,
        created_at: now, updated_at: now, last_error: STANDALONE_ARRANGE_NOTICE,
      }
      state.jobs.unshift(created)
      state.occurrences[created.id] = []
      await this.save()
      return { job: created, scheduler_available: false, scheduler_notice: STANDALONE_ARRANGE_NOTICE }
    }
    if (method === 'arrange.occurrence.list') {
      if (!job) throw new Error('安排不存在')
      return { occurrences: state.occurrences[id] || [] }
    }
    if (method === 'arrange.occurrence.get') {
      const occurrence = (state.occurrences[id] || []).find(value => value.id === params.occurrence_id)
      if (!occurrence) throw new Error('运行记录不存在')
      return { occurrence }
    }
    if (!job) throw new Error('安排不存在')
    if (method === 'arrange.get') return { job }
    if (method === 'arrange.resume' || method === 'arrange.signal') throw new Error(STANDALONE_ARRANGE_NOTICE)
    if (method === 'arrange.pause') {
      job.status = 'paused'
    } else if (method === 'arrange.cancel') {
      job.status = 'cancelled'
    } else if (method === 'arrange.update') {
      if (job.status === 'cancelled') throw new Error('已取消安排不能编辑')
      if (typeof params.title === 'string') job.title = params.title
      if (typeof params.instruction === 'string') {
        if (!params.instruction.trim()) throw new Error('安排指令不能为空')
        job.payload = { ...job.payload, message: params.instruction.trim() }
      }
      if (params.trigger) {
        const trigger = record(params.trigger)
        if (!['once', 'interval', 'calendar', 'event'].includes(String(trigger.type || ''))) throw new Error('安排触发方式无效')
        job.trigger = trigger
      }
      if (params.session_strategy) job.session_strategy = String(params.session_strategy)
      if ('model_id' in params) job.model_id = String(params.model_id || '')
      job.status = 'paused'
      job.last_error = STANDALONE_ARRANGE_NOTICE
    } else throw new Error(`本机模式不支持 ${method}`)
    job.updated_at = new Date().toISOString()
    job.revision += 1
    await this.save()
    return { job, scheduler_available: false, scheduler_notice: STANDALONE_ARRANGE_NOTICE }
  }

  private async load(): Promise<State> {
    if (this.state) return this.state
    const saved = await this.storage.read()
    this.state = { jobs: Array.isArray(saved?.jobs) ? saved.jobs : [], occurrences: saved?.occurrences || {} }
    return this.state
  }

  private async save(): Promise<void> {
    if (this.state) await this.storage.write(this.state)
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function positiveNumber(value: unknown): number | null {
  const number = Number(value)
  return Number.isInteger(number) && number > 0 ? number : null
}
