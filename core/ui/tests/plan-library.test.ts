import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PlanLibraryPanel from '../src/plans/PlanLibraryPanel.vue'
import RightSidebarHost from '../src/components/RightSidebarHost.vue'
import { usePlanLibrary } from '../src/plans/usePlanLibrary'
import {
  buildPlanPatch,
  emptyPlan,
  extractPlan,
  extractPlans,
  extractRevisions,
  isRevisionConflict,
  planStatusTargets,
  sanitizePlan,
  validatePlanDraft,
} from '../src/plans/planEditing'
import type { PlanPackage } from '../src/plans/types'

const HERE = dirname(fileURLToPath(import.meta.url))

function plan(overrides: Partial<PlanPackage> = {}): PlanPackage {
  return {
    schema_version: 1,
    plan_id: 'plan_a',
    title: '移动端方案库',
    status: 'draft',
    summary: '手机做方案，电脑执行',
    requirement: {
      restatement: '手机起草，电脑执行',
      success_looks_like: '两端都能编辑同一份方案',
      non_goals: ['不做多人协作'],
      assumptions: ['有网'],
    },
    open_questions: [{ id: 'q1', question: '谁拍板？', status: 'open', answer: '' }],
    approach: {
      chosen: '共享界面 + 现有 RPC',
      why: '两端一致',
      rejected: [{ option: '各写一套', why: '会漂移' }],
    },
    checklist: {
      design_summary: '分批交付',
      steps: [
        { id: 's1', description: '先做列表', deliverables: ['列表组件'], status: 'pending' },
        { id: 's2', description: '再做编辑', deliverables: [], status: 'in_progress' },
      ],
      files: ['src/plans/planEditing.ts'],
    },
    goal: { objective: '让手机能出方案', completion_criteria: ['两端字段一致'] },
    risks: [{ risk: '契约漂移', severity: 'medium', mitigation: '共享样例集' }],
    docs: [{ path: 'plans/design.md', kind: 'design', title: '设计文档' }],
    execution: null,
    project_id: 'proj-1',
    source: 'desktop',
    revision: 3,
    created_at: '2026-09-28T00:00:00Z',
    updated_at: '2026-09-28T01:00:00Z',
    deleted_at: null,
    ...overrides,
  }
}

function clone(value: PlanPackage): PlanPackage {
  return JSON.parse(JSON.stringify(value)) as PlanPackage
}

function saveCall(requestRpc: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const call = requestRpc.mock.calls.find((entry) => entry[0] === 'plan.save')
  expect(call, 'plan.save was called').toBeTruthy()
  return (call?.[1] || {}) as Record<string, unknown>
}

// ---------------------------------------------------------------------------
// ③④ patch building — pure, no RPC
// ---------------------------------------------------------------------------

describe('plan editing patch', () => {
  it('sends only the changed step status plus expected_revision when one step moves', () => {
    const original = plan()
    const draft = clone(original)
    draft.checklist.steps[0].status = 'completed'

    const patch = buildPlanPatch(original, draft)
    expect(Object.keys(patch).sort()).toEqual(['checklist', 'expected_revision', 'plan_id', 'project_id'])
    expect(patch.plan_id).toBe('plan_a')
    expect(patch.expected_revision).toBe(3)
    expect(patch.checklist?.steps[0].status).toBe('completed')
    // A true patch: nothing else rides along.
    expect(patch.title).toBeUndefined()
    expect(patch.requirement).toBeUndefined()
    expect(patch.approach).toBeUndefined()
    expect(patch.goal).toBeUndefined()
  })

  it('carries an answered question without touching unrelated fields', () => {
    const original = plan()
    const draft = clone(original)
    draft.open_questions[0].status = 'answered'
    draft.open_questions[0].answer = '产品负责人'

    const patch = buildPlanPatch(original, draft)
    expect(patch.open_questions).toEqual([
      { id: 'q1', question: '谁拍板？', status: 'answered', answer: '产品负责人' },
    ])
    expect(patch.requirement).toBeUndefined()
    expect(patch.approach).toBeUndefined()
    expect(patch.checklist).toBeUndefined()
  })

  it('omits expected_revision for a brand-new plan', () => {
    const patch = buildPlanPatch(null, { ...emptyPlan('proj-1'), title: '新方案' })
    expect(patch.expected_revision).toBeUndefined()
    expect(patch.project_id).toBe('proj-1')
    expect(patch.title).toBe('新方案')
    expect(patch.requirement).toBeDefined()
    expect(patch.approach).toBeDefined()
  })

  it('offers only the contract status transitions and refuses an empty ready plan', () => {
    expect(planStatusTargets('draft')).toEqual(['ready', 'archived'])
    expect(planStatusTargets('archived')).toEqual([])
    const empty = { ...emptyPlan('proj-1'), title: '空清单', requirement: { restatement: 'x', success_looks_like: '', non_goals: [], assumptions: [] }, approach: { chosen: 'y', why: '', rejected: [] }, status: 'ready' as const }
    expect(validatePlanDraft(empty)).toBe('定稿（就绪）至少需要一步')
    expect(validatePlanDraft({ ...empty, title: '' })).toBe('标题不能为空')
  })

  it('trims and drops blanks the way the host stores them', () => {
    const dirty = plan({
      title: '  整理  ',
      requirement: { restatement: ' x ', success_looks_like: '', non_goals: ['  不做  ', '  ', ''], assumptions: [] },
    })
    const clean = sanitizePlan(dirty)
    expect(clean.title).toBe('整理')
    expect(clean.requirement.non_goals).toEqual(['不做'])
  })

  it('extracts host payloads and detects the concurrency refusal', () => {
    expect(extractPlans({ plans: [plan()] })).toHaveLength(1)
    expect(extractPlan({ plan: plan() })?.plan_id).toBe('plan_a')
    expect(extractRevisions({ revisions: [{ revision: 1, title: 'v1', status: 'draft', source: 'desktop', created_at: '' }] })).toHaveLength(1)
    expect(isRevisionConflict(new Error('plan revision conflict: plan_a'))).toBe(true)
    expect(isRevisionConflict(new Error('plan title is required'))).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// ③④⑤⑥ composable — the exact RPC the panel emits
// ---------------------------------------------------------------------------

function rpcFixture(overrides: Record<string, (params: Record<string, unknown>) => unknown> = {}) {
  return vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    const override = overrides[method]
    if (override) return override(params) as Record<string, unknown>
    if (method === 'plan.list') return { plans: [plan()] }
    if (method === 'plan.get') return { plan: plan() }
    if (method === 'plan.revisions') return { revisions: [{ revision: 1, title: 'v1', status: 'draft', source: 'desktop', created_at: '' }] }
    if (method === 'plan.save') return { plan: plan({ revision: 4 }) }
    if (method === 'plan.revert') return { plan: plan({ revision: 5 }) }
    if (method === 'plan.delete') return { plan: plan({ deleted_at: '2026-09-28T02:00:00Z' }) }
    if (method === 'plan.restore') return { plan: plan() }
    return {}
  })
}

describe('usePlanLibrary', () => {
  it('sends the step-status patch with expected_revision and reloads after saving', async () => {
    const requestRpc = rpcFixture({
      'plan.save': (params) => ({ plan: plan({ revision: 4, checklist: { ...plan().checklist, steps: [{ ...plan().checklist.steps[0], status: (params.checklist as PlanPackage['checklist']).steps[0].status }, plan().checklist.steps[1]] } }) }),
    })
    const lib = usePlanLibrary({ requestRpc, projectId: () => 'proj-1' })
    lib.selectPlan(plan())
    await flushPromises()

    lib.draft.checklist.steps[0].status = 'completed'
    const ok = await lib.save()
    expect(ok).toBe(true)

    const params = saveCall(requestRpc)
    expect(params.plan_id).toBe('plan_a')
    expect(params.expected_revision).toBe(3)
    expect((params.checklist as PlanPackage['checklist']).steps[0].status).toBe('completed')
    expect(params.title).toBeUndefined()
    expect(params.requirement).toBeUndefined()
    expect(lib.draft.checklist.steps[0].status).toBe('completed')
    expect(lib.dirty.value).toBe(false)
  })

  it('answers an open question: status becomes answered and the answer rides the patch', async () => {
    const requestRpc = rpcFixture()
    const lib = usePlanLibrary({ requestRpc, projectId: () => 'proj-1' })
    lib.selectPlan(plan())
    await flushPromises()

    lib.draft.open_questions[0].status = 'answered'
    lib.draft.open_questions[0].answer = '产品负责人'
    expect(await lib.save()).toBe(true)

    const params = saveCall(requestRpc)
    expect(params.open_questions).toEqual([
      { id: 'q1', question: '谁拍板？', status: 'answered', answer: '产品负责人' },
    ])
    expect(params.requirement).toBeUndefined()
  })

  it('on a revision conflict: tells the user, reloads the latest, never overwrites', async () => {
    const requestRpc = rpcFixture({
      'plan.save': () => { throw new Error('plan revision conflict: plan_a') },
      'plan.get': () => ({ plan: plan({ revision: 5, title: '别人改过的标题' }) }),
      'plan.list': () => ({ plans: [plan({ revision: 5, title: '别人改过的标题' })] }),
    })
    const lib = usePlanLibrary({ requestRpc, projectId: () => 'proj-1' })
    lib.selectPlan(plan())
    await flushPromises()

    lib.draft.title = '我的改动'
    expect(await lib.save()).toBe(false)

    expect(lib.conflictNotice.value).toContain('重新载入')
    expect(lib.draft.title).toBe('别人改过的标题')
    expect(lib.savedSnapshot.value?.revision).toBe(5)
    expect(requestRpc).toHaveBeenCalledWith('plan.get', { plan_id: 'plan_a' })
    // One and only one save attempt: the stale write was refused, not retried.
    expect(requestRpc.mock.calls.filter((entry) => entry[0] === 'plan.save')).toHaveLength(1)
  })

  it('calls revert / delete / restore with the documented payloads', async () => {
    const requestRpc = rpcFixture()
    const lib = usePlanLibrary({ requestRpc, projectId: () => 'proj-1' })
    lib.selectPlan(plan())
    await flushPromises()

    expect(await lib.revert(1)).toBe(true)
    expect(requestRpc).toHaveBeenCalledWith('plan.revert', { plan_id: 'plan_a', revision: 1 })

    await lib.remove('plan_a')
    expect(requestRpc).toHaveBeenCalledWith('plan.delete', { plan_id: 'plan_a' })

    await lib.restore('plan_a')
    expect(requestRpc).toHaveBeenCalledWith('plan.restore', { plan_id: 'plan_a' })
  })

  it('① filters the list by project, status and deleted', async () => {
    const requestRpc = rpcFixture({ 'plan.list': () => ({ plans: [] }) })
    const lib = usePlanLibrary({ requestRpc, projectId: () => 'proj-1' })
    expect(lib.projectFilter.value).toBe('proj-1')

    await lib.refresh()
    expect(requestRpc).toHaveBeenLastCalledWith('plan.list', { include_deleted: false, project_id: 'proj-1' })

    lib.setStatusFilter('ready')
    await flushPromises()
    expect(requestRpc).toHaveBeenLastCalledWith('plan.list', { include_deleted: false, project_id: 'proj-1', status: 'ready' })

    lib.toggleDeleted()
    await flushPromises()
    expect(requestRpc).toHaveBeenLastCalledWith('plan.list', { include_deleted: true, project_id: 'proj-1', status: 'ready' })

    lib.setProjectFilter('')
    await flushPromises()
    expect(requestRpc).toHaveBeenLastCalledWith('plan.list', { include_deleted: true, status: 'ready' })
    expect(lib.projectFilter.value).toBe('')
  })
})

// ---------------------------------------------------------------------------
// ①②⑦⑧ panel rendering and actions
// ---------------------------------------------------------------------------

describe('PlanLibraryPanel', () => {
  it('① shows an empty state that points at letting the assistant draft one', async () => {
    const requestRpc = vi.fn(async (method: string) => (method === 'plan.list' ? { plans: [] } : method === 'project.list' ? { projects: [{ id: 'proj-1', name: 'Core' }] } : {}))
    const wrapper = mount(PlanLibraryPanel, { props: { projectId: 'proj-1', requestRpc } })
    await flushPromises()

    expect(wrapper.get('[data-plan-empty]').text()).toContain('让助手先起草一份方案')
    // project + status filters are present
    expect(wrapper.findAll('.ui-select').length).toBeGreaterThanOrEqual(2)
    wrapper.unmount()
  })

  it('② renders every section of a stored package once a plan is opened', async () => {
    const requestRpc = rpcFixture()
    const wrapper = mount(PlanLibraryPanel, { props: { projectId: 'proj-1', requestRpc } })
    await flushPromises()

    expect(wrapper.get('[data-plan-id="plan_a"]').text()).toContain('移动端方案库')
    await wrapper.get('.plan-item-main').trigger('click')
    await flushPromises()

    for (const block of ['requirement', 'approach', 'docs', 'steps', 'goal', 'risks', 'questions', 'revisions']) {
      expect(wrapper.find(`[data-plan-block="${block}"]`).exists(), block).toBe(true)
    }
    const text = wrapper.text()
    expect(text).toContain('需求')
    expect(text).toContain('取舍')
    expect(text).toContain('明确不做')
    expect(text).toContain('被否决的方案')
    expect(text).toContain('交付物')
    expect(text).toContain('完成判据')
    expect(text).toContain('风险')
    expect(text).toContain('未答问题')
    expect(text).toContain('版本')
    // Prose fields live in inputs/textareas, so read their live values.
    const values = [
      ...wrapper.findAll('input').map((el) => (el.element as HTMLInputElement).value),
      ...wrapper.findAll('textarea').map((el) => (el.element as HTMLTextAreaElement).value),
    ]
    expect(values).toContain('手机起草，电脑执行')
    expect(values).toContain('共享界面 + 现有 RPC')
    expect(values).toContain('契约漂移')
    expect(values).toContain('谁拍板？')
    wrapper.unmount()
  })

  it('⑦ starts work only from a ready plan and emits the plan as a turn', async () => {
    const requestRpc = rpcFixture({ 'plan.list': () => ({ plans: [plan({ status: 'ready', revision: 4 })] }) })
    const wrapper = mount(PlanLibraryPanel, { props: { projectId: 'proj-1', requestRpc } })
    await flushPromises()

    await wrapper.get('.plan-item-main').trigger('click')
    await flushPromises()
    const start = wrapper.get('[data-plan-start]')
    expect(start.attributes('disabled')).toBeUndefined()
    await start.trigger('click')

    const emitted = wrapper.emitted('start-plan')
    expect(emitted).toBeTruthy()
    expect((emitted?.[0]?.[0] as PlanPackage).plan_id).toBe('plan_a')
    wrapper.unmount()
  })

  it('⑦ keeps 开工 disabled while the plan is only a draft', async () => {
    const requestRpc = rpcFixture()
    const wrapper = mount(PlanLibraryPanel, { props: { projectId: 'proj-1', requestRpc } })
    await flushPromises()
    await wrapper.get('.plan-item-main').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-plan-start]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-plan-start]').attributes('title')).toContain('就绪')
    wrapper.unmount()
  })

  it('④ answers an open question from the form: it flips to answered and saves that way', async () => {
    const saved: Record<string, unknown>[] = []
    const requestRpc = rpcFixture({
      'plan.save': (params) => {
        saved.push(params)
        return { plan: plan({ revision: 4 }) }
      },
    })
    const wrapper = mount(PlanLibraryPanel, { props: { projectId: 'proj-1', requestRpc } })
    await flushPromises()
    await wrapper.get('.plan-item-main').trigger('click')
    await flushPromises()

    await wrapper.get('textarea[placeholder="写下答案即转为已答"]').setValue('产品负责人')
    await wrapper.get('.plan-action--primary').trigger('click')
    await flushPromises()

    expect(saved).toHaveLength(1)
    expect(saved[0].expected_revision).toBe(3)
    expect(saved[0].open_questions).toEqual([
      { id: 'q1', question: '谁拍板？', status: 'answered', answer: '产品负责人' },
    ])
    wrapper.unmount()
  })

  it('exposes the workbench as a right-rail mode beside 运行/文件/成果', async () => {
    const requestRpc = vi.fn(async (method: string) => (method === 'plan.list' ? { plans: [] } : {}))
    const wrapper = mount(RightSidebarHost, {
      props: { storageKey: 'test.plans.mode', projectId: 'proj-1', requestRpc },
    })
    await flushPromises()

    const labels = wrapper.findAll('[role="tab"]').map((tab) => tab.text())
    expect(labels).toContain('方案')
    ;(wrapper.vm as unknown as { selectMode: (mode: 'plans') => void }).selectMode('plans')
    await flushPromises()
    expect(wrapper.find('[data-plan-library]').exists()).toBe(true)
    wrapper.unmount()
  })
})

// ---------------------------------------------------------------------------
// ⑧ narrow screens + long text
// ---------------------------------------------------------------------------

describe('PlanLibraryPanel narrow-screen contract', () => {
  it('carries a <=640px layout and keeps long text from overflowing', () => {
    const source = readFileSync(resolve(HERE, '../src/plans/PlanLibraryPanel.vue'), 'utf8')
    expect(source).toMatch(/@media \(max-width: 640px\)/)
    expect(source).toMatch(/overflow-wrap: anywhere/)
    expect(source).toMatch(/min-width: 0/)
    expect(source).toMatch(/text-overflow: ellipsis/)

    const stringList = readFileSync(resolve(HERE, '../src/plans/PlanStringListEditor.vue'), 'utf8')
    expect(stringList).toMatch(/@media \(max-width: 640px\)/)
    expect(stringList).toMatch(/min-width: 0/)
  })

  it('renders a very long unbroken title without dropping it', async () => {
    const long = 'x'.repeat(600)
    const requestRpc = rpcFixture({ 'plan.list': () => ({ plans: [plan({ title: long })] }) })
    const wrapper = mount(PlanLibraryPanel, { props: { projectId: 'proj-1', requestRpc } })
    await flushPromises()

    expect(wrapper.get('.plan-title').text()).toBe(long)
    wrapper.unmount()
  })
})
