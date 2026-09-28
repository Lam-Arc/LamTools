import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { planRpc } from '../src/standalone/StandalonePlans'

/**
 * The shared contract, read from the same file the desktop and the mobile Rust
 * store run. The rules themselves are proven in Rust (`plans.rs`); what this
 * file pins is the bridge in front of them: every action the fixtures describe
 * must be reachable through `plan.*`, with the payloads and the camelCase
 * spellings the desktop accepts.
 */
const CONTRACT = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../protocol/plan-package-v1-fixtures.json', import.meta.url)), 'utf-8'),
) as {
  cases: Array<{ name: string; action: string; given?: Array<{ action?: string; payload?: Record<string, unknown> }> }>
}

const PLAN = {
  schema_version: 1,
  plan_id: 'plan_1',
  title: '移动端方案库',
  status: 'draft',
  summary: '',
  requirement: { restatement: '手机做方案', success_looks_like: '', non_goals: [], assumptions: [] },
  open_questions: [],
  approach: { chosen: '共享插件', why: '', rejected: [] },
  checklist: { design_summary: '', steps: [], files: [] },
  goal: { objective: '', completion_criteria: [] },
  risks: [],
  docs: [],
  execution: null,
  project_id: 'proj-1',
  source: 'mobile',
  revision: 1,
  created_at: '2026-09-28T00:00:00Z',
  updated_at: '2026-09-28T00:00:00Z',
  deleted_at: null,
}

afterEach(() => {
  invokeMock.mockReset()
  vi.unstubAllGlobals()
})

function stubHost(): void {
  vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
}

describe('standalone plans', () => {
  it('does not answer the plan RPCs outside the embedded host', async () => {
    await expect(planRpc('plan.list', {})).rejects.toThrow('移动端独立模式不支持 plan.list')
    await expect(planRpc('goal.list', {})).resolves.toBeNull()
  })

  it('sends the package itself and normalises the concurrency token', async () => {
    stubHost()
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
      if (command === 'sunday_plan_save') {
        expect(args.payload).toEqual({
          plan_id: 'plan_1',
          title: '改过的标题',
          expected_revision: 2,
        })
        return { plan: { ...PLAN, title: '改过的标题', revision: 3 } }
      }
      throw new Error(`unexpected ${command}`)
    })

    await planRpc('plan.save', { plan_id: 'plan_1', title: '改过的标题', expected_revision: '2' })
    expect(invokeMock).toHaveBeenCalledTimes(1)

    // The camelCase spelling the desktop also accepts needs the same treatment.
    await planRpc('plan.save', { planId: 'plan_1', title: '改过的标题', expectedRevision: 2 })
    expect(invokeMock).toHaveBeenCalledTimes(2)

    // A save with no token must not send an empty one: absent means "no check",
    // which is different from "check against nothing".
    invokeMock.mockImplementation(async () => ({ plan: PLAN }))
    await planRpc('plan.save', { plan_id: 'plan_1', title: '没什么要检查' })
    const payload = invokeMock.mock.calls[2][1].payload as Record<string, unknown>
    expect('expected_revision' in payload).toBe(false)
    expect('expectedRevision' in payload).toBe(false)
  })

  it('passes list filters through, including the deleted ones', async () => {
    stubHost()
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown>) => {
      expect(command).toBe('sunday_plan_list')
      return { plans: [PLAN] }
    })

    await planRpc('plan.list', {})
    expect(invokeMock).toHaveBeenLastCalledWith('sunday_plan_list', {
      projectId: null,
      status: null,
      includeDeleted: false,
    })

    await planRpc('plan.list', { project_id: 'proj-1', status: 'draft', include_deleted: true })
    expect(invokeMock).toHaveBeenLastCalledWith('sunday_plan_list', {
      projectId: 'proj-1',
      status: 'draft',
      includeDeleted: true,
    })

    // The panel reads `includeDeleted` from its own state too.
    await planRpc('plan.list', { includeDeleted: true })
    expect(invokeMock).toHaveBeenLastCalledWith('sunday_plan_list', {
      projectId: null,
      status: null,
      includeDeleted: true,
    })
  })

  it('reaches every lifecycle command with the id the caller spelled', async () => {
    stubHost()
    const seen: string[] = []
    invokeMock.mockImplementation(async (command: string) => {
      seen.push(command)
      return command === 'sunday_plan_revisions' ? { revisions: [] } : { plan: PLAN }
    })

    await planRpc('plan.get', { plan_id: 'plan_1' })
    await planRpc('plan.get', { planId: 'plan_1' })
    await planRpc('plan.get', { id: 'plan_1' })
    await planRpc('plan.delete', { plan_id: 'plan_1' })
    await planRpc('plan.restore', { plan_id: 'plan_1' })
    await planRpc('plan.revert', { plan_id: 'plan_1', revision: 1 })
    await planRpc('plan.revisions', { plan_id: 'plan_1' })

    expect(seen).toEqual([
      'sunday_plan_get',
      'sunday_plan_get',
      'sunday_plan_get',
      'sunday_plan_delete',
      'sunday_plan_restore',
      'sunday_plan_revert',
      'sunday_plan_revisions',
    ])
    expect(invokeMock).toHaveBeenLastCalledWith('sunday_plan_revisions', { planId: 'plan_1' })
  })

  it('refuses a missing id and an unusable revision before reaching the host', async () => {
    stubHost()
    invokeMock.mockResolvedValue({ plan: PLAN })

    await expect(planRpc('plan.get', {})).rejects.toThrow('plan_id is required')
    await expect(planRpc('plan.delete', {})).rejects.toThrow('plan_id is required')
    await expect(planRpc('plan.revert', { plan_id: 'plan_1' })).rejects.toThrow('plan revision must be a number')
    await expect(planRpc('plan.revert', { plan_id: 'plan_1', revision: 'abc' })).rejects.toThrow(
      'plan revision must be a number',
    )
    expect(invokeMock).not.toHaveBeenCalled()
  })

  it('every action the shared fixtures describe has an RPC behind it', async () => {
    stubHost()
    invokeMock.mockResolvedValue({ plan: PLAN, plans: [], revisions: [] })

    const actions = new Set<string>()
    for (const testCase of CONTRACT.cases) {
      actions.add(testCase.action)
      for (const step of testCase.given || []) actions.add(step.action || 'save')
    }
    expect([...actions].sort()).toEqual(['delete', 'list', 'restore', 'revert', 'revisions', 'save'])

    // Each one goes through a `plan.*` method this bridge actually answers, and
    // none of them falls through to the "unsupported method" refusal.
    for (const action of actions) {
      const method = `plan.${action}`
      const params = action === 'revert' ? { plan_id: 'plan_1', revision: 1 } : { plan_id: 'plan_1' }
      await expect(planRpc(method, params), `${method} has no handler`).resolves.not.toBeNull()
    }
  })
})
