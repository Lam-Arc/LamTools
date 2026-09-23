import { describe, expect, it, vi } from 'vitest'
import { createLocalRepository, type LocalState } from '../src/storage'
import type { LocalDatabase } from '../src/storage/Database'
import { StandaloneTransport, type WorkflowCall } from '../src/standalone/StandaloneTransport'

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

describe('native Workflow document route', () => {
  it('resolves a project from the local repository and ignores caller work_root', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const { project, thread } = await repository.createLocalProject({ name: 'Project' })
    const workflowCall = vi.fn(async () => ({ workflows: [] })) as WorkflowCall & ReturnType<typeof vi.fn>
    const transport = new StandaloneTransport(repository, undefined, undefined, undefined, undefined, undefined, undefined, workflowCall)
    const params = { session_id: thread.id, work_root: '../outside', name: 'demo' }

    expect(await transport.request({ method: 'workflow.list', params })).toEqual({ workflows: [] })
    expect(workflowCall).toHaveBeenCalledWith({ method: 'workflow.list', params, projectId: project.id })
    await expect(transport.request({ method: 'workflow.get', params: {
      ...params, project_id: 'other-project',
    } })).rejects.toThrow('工作流项目与会话不匹配')
    expect(workflowCall).toHaveBeenCalledTimes(1)
  })

  it('uses global storage without a selected project and rejects unregistered ids', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const workflowCall = vi.fn(async () => ({ workflows: [] })) as WorkflowCall & ReturnType<typeof vi.fn>
    const transport = new StandaloneTransport(repository, undefined, undefined, undefined, undefined, undefined, undefined, workflowCall)

    await transport.request({ method: 'workflow.list', params: { work_root: '/tmp/attacker' } })
    expect(workflowCall).toHaveBeenCalledWith({ method: 'workflow.list', params: { work_root: '/tmp/attacker' } })
    await expect(transport.request({ method: 'workflow.document.save', params: {
      project_id: '../outside', document: {},
    } })).rejects.toThrow('项目不存在')
    expect(workflowCall).toHaveBeenCalledTimes(1)
  })
})
