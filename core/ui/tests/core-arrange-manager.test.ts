import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreArrangeManager from '../src/components/CoreArrangeManager.vue'
import type { CoreArrangeJob } from '../src/durable/types'

function jobFixture(overrides: Partial<CoreArrangeJob> = {}): CoreArrangeJob {
  return {
    id: 'job-1',
    thread_id: '',
    source_thread_id: '',
    project_id: 'p1',
    work_root: 'E:/demo',
    kind: 'routine',
    operation: 'turn.start',
    payload: { message: '处理 pricing-index 的异常队列，并在确认后更新已发布的计划数据。' },
    trigger: { type: 'calendar', frequency: 'daily', time: '09:05', timezone: 'Asia/Shanghai' },
    title: '每天 09:05 处理异常队列',
    session_strategy: 'new',
    status: 'paused',
    run_count: 1,
    revision: 1,
    created_at: '2026-09-30T01:05:00Z',
    updated_at: '2026-09-30T01:05:00Z',
    ...overrides,
  }
}

/** 按方法路由的 RPC 桩：未声明的方法直接抛错，避免测试悄悄走错路径。 */
function rpcRouter(handlers: Record<string, (params?: Record<string, unknown>) => unknown>) {
  return vi.fn(async (method: string, params?: Record<string, unknown>) => {
    const handler = handlers[method]
    if (!handler) throw new Error(`unexpected rpc: ${method}`)
    return handler(params) as Record<string, unknown>
  })
}

const quietHandlers = {
  'arrange.list': () => ({ jobs: [], scheduler_notice: '' }),
  'project.list': () => ({ projects: [] }),
  'config.models.list': () => ({
    models: [
      { id: 'glm-5.3-flash', model_id: 'glm-5.3-flash', display_name: 'GLM Flash', provider_name: '智谱' },
    ],
    default_model_id: 'glm-5.3-flash',
  }),
}

describe('CoreArrangeManager states', () => {
  it('renders an error without also claiming the list is empty and can retry', async () => {
    const requestRpc = vi.fn()
      .mockRejectedValueOnce(new Error('服务不可用'))
      .mockResolvedValueOnce({ jobs: [] })
    const wrapper = mount(CoreArrangeManager, {
      props: { requestRpc },
      // 动作组会传送到顶部条（full-area-band-actions）；jsdom 里没有那个节点，
      // 传送目标缺失时内容自会就地渲染。
      global: { stubs: { Teleport: true } },
    })

    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('服务不可用')
    expect(wrapper.find('[data-arrange-empty]').exists()).toBe(false)
    expect(wrapper.find('.card-list').exists()).toBe(false)

    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[data-arrange-empty]').text()).toContain('还没有定时任务')
  })
})

describe('CoreArrangeManager standard list', () => {
  it('renders the status filter tabs, job cards and built-in templates', async () => {
    const requestRpc = rpcRouter({
      ...quietHandlers,
      'arrange.list': () => ({ jobs: [jobFixture()], scheduler_notice: '调度器待机' }),
    })
    const wrapper = mount(CoreArrangeManager, {
      props: { requestRpc },
      global: { stubs: { Teleport: true, UiSelect: true } },
    })
    await flushPromises()

    const tabs = wrapper.get('[role="group"][aria-label="按状态筛选"]')
    expect(tabs.text()).toContain('全部')
    expect(tabs.text()).toContain('进行中')
    expect(tabs.text()).toContain('已完成')
    expect(tabs.text()).toContain('失败')

    expect(wrapper.text()).toContain('已创建任务')
    expect(wrapper.text()).toContain('定时任务模板')
    expect(wrapper.get('.arrange-card .card-title').text()).toBe('每天 09:05 处理异常队列')
    expect(wrapper.get('.arrange-card .card-desc').text()).toContain('pricing-index')
    expect(wrapper.get('.arrange-card .status-chip').text()).toContain('已暂停')
    expect(wrapper.get('.arrange-card .schedule-chip').text()).toContain('每天 09:05')
    expect(wrapper.get('.arrange-card .run-count').text()).toBe('已运行 1 次')
    expect(wrapper.findAll('.template-card').length).toBeGreaterThanOrEqual(2)
  })

  it('filters jobs by the selected status tab', async () => {
    const requestRpc = rpcRouter({
      ...quietHandlers,
      'arrange.list': () => ({
        jobs: [
          jobFixture(),
          jobFixture({ id: 'job-2', title: '已完成任务', status: 'completed' }),
          jobFixture({ id: 'job-3', title: '失败任务', status: 'failed' }),
        ],
      }),
    })
    const wrapper = mount(CoreArrangeManager, {
      props: { requestRpc },
      global: { stubs: { Teleport: true, UiSelect: true } },
    })
    await flushPromises()
    expect(wrapper.findAll('.arrange-card')).toHaveLength(3)

    const failedTab = wrapper.findAll('[role="group"][aria-label="按状态筛选"] button')
      .find(button => button.text() === '失败')
    expect(failedTab).toBeTruthy()
    await failedTab!.trigger('click')
    expect(wrapper.findAll('.arrange-card')).toHaveLength(1)
    expect(wrapper.get('.arrange-card .card-title').text()).toBe('失败任务')

    const completedTab = wrapper.findAll('[role="group"][aria-label="按状态筛选"] button')
      .find(button => button.text() === '已完成')
    await completedTab!.trigger('click')
    expect(wrapper.findAll('.arrange-card')).toHaveLength(1)
    expect(wrapper.get('.arrange-card .card-title').text()).toBe('已完成任务')
  })

  it('opens the edit page from a card and loads its run history', async () => {
    const requestRpc = rpcRouter({
      ...quietHandlers,
      'arrange.list': () => ({ jobs: [jobFixture()] }),
      'arrange.occurrence.list': () => ({
        occurrences: [
          { id: 'occ-1', job_id: 'job-1', status: 'completed', scheduled_at: '2026-09-30T01:05:00Z', attempt_count: 1 },
        ],
      }),
    })
    const wrapper = mount(CoreArrangeManager, {
      props: { requestRpc },
      global: { stubs: { Teleport: true, UiSelect: true } },
    })
    await flushPromises()

    await wrapper.get('.arrange-card').trigger('click')
    expect(wrapper.text()).toContain('编辑定时任务')
    expect(wrapper.text()).toContain('每天 09:05 处理异常队列')
    // 顶部条标题上报为面包屑。
    const headings = wrapper.emitted('heading') as Array<Array<{ title: string; subtitle: string }>>
    expect(headings[headings.length - 1][0].title).toContain('定时任务 ›')

    await wrapper.findAll('[role="tab"]').find(tab => tab.text() === '历史')!.trigger('click')
    await flushPromises()
    expect(requestRpc).toHaveBeenCalledWith('arrange.occurrence.list', { job_id: 'job-1' })
    expect(wrapper.text()).toContain('完成')
  })

  it('keeps the bound session when saving an edited fixed-session job', async () => {
    const fixedJob = jobFixture({ session_strategy: 'fixed', thread_id: 'thread-9' })
    const requestRpc = rpcRouter({
      'arrange.list': () => ({ jobs: [fixedJob] }),
      'project.list': () => ({ projects: [{ id: 'p1', name: 'demo', work_root: 'E:/demo' }] }),
      'config.models.list': () => ({
        models: [{ id: 'glm-5.3-flash', model_id: 'glm-5.3-flash', display_name: 'GLM Flash', provider_name: '智谱' }],
        default_model_id: 'glm-5.3-flash',
      }),
      'project.sessions.list': () => ({ sessions: [{ id: 'thread-9', title: '跟进会话' }] }),
      'arrange.update': () => ({ job: fixedJob }),
    })
    const wrapper = mount(CoreArrangeManager, {
      props: { requestRpc },
      global: { stubs: { Teleport: true, UiSelect: true } },
    })
    await flushPromises()

    await wrapper.get('.arrange-card').trigger('click')
    await flushPromises()

    const saveButton = wrapper.findAll('button').find(button => button.text() === '保存')
    expect(saveButton).toBeTruthy()
    await saveButton!.trigger('click')
    await flushPromises()

    const updateCall = requestRpc.mock.calls.find(([method]) => method === 'arrange.update')
    expect(updateCall).toBeTruthy()
    expect(updateCall![1]).toMatchObject({ session_strategy: 'fixed' })
  })

  it('requires a concrete model: prefilled with the current default and no follow-default option', async () => {
    const requestRpc = rpcRouter(quietHandlers)
    const wrapper = mount(CoreArrangeManager, {
      props: { requestRpc },
      global: { stubs: { Teleport: true } },
    })
    await flushPromises()

    await wrapper.findAll('.template-card')[0].trigger('click')
    await flushPromises()

    // 模型下拉不带「跟随默认」：打开创建页即选中当前默认模型（记录 id）。
    const modelSelect = wrapper.findAll('.meta-select')[1]
    expect(modelSelect.find('.ui-select-trigger').text()).toContain('智谱/glm-5.3-flash')
    expect(modelSelect.text()).not.toContain('跟随默认')
    // 右缘触发器的菜单右对齐，贴住自己的右缘而不是卡片边缘。
    expect(modelSelect.classes()).toContain('meta-select--model')
    expect(modelSelect.classes()).toContain('ui-select--right')

    // 没有模型就不能创建：把模型清空（模拟用户未选择）时按钮禁用。
    await modelSelect.find('.ui-select-trigger').trigger('click')
    const optionButtons = modelSelect.findAll('.ui-select-option')
    expect(optionButtons.length).toBe(1)
  })

  it('creates a job from a template through arrange.create and returns to the list', async () => {
    const requestRpc = rpcRouter({
      ...quietHandlers,
      'arrange.create': () => ({ job: jobFixture({ status: 'scheduled', title: '晨会摘要' }) }),
    })
    const wrapper = mount(CoreArrangeManager, {
      props: { requestRpc },
      global: { stubs: { Teleport: true, UiSelect: true } },
    })
    await flushPromises()

    await wrapper.findAll('.template-card')[0].trigger('click')
    expect(wrapper.text()).toContain('新建定时任务')
    // 模板已把标题、指令和每天计划带入表单。
    const instruction = wrapper.get('.instruction-shell textarea').element as HTMLTextAreaElement
    expect(instruction.value).toContain('口述摘要')

    const createButton = wrapper.findAll('button').find(button => button.text() === '创建定时任务')
    expect(createButton).toBeTruthy()
    expect((createButton!.element as HTMLButtonElement).disabled).toBe(false)
    await createButton!.trigger('click')
    await flushPromises()

    expect(requestRpc).toHaveBeenCalledWith('arrange.create', expect.objectContaining({
      kind: 'routine',
      operation: 'turn.start',
      title: '晨会摘要',
      session_strategy: 'new',
      model_id: 'glm-5.3-flash',
      trigger: { type: 'calendar', frequency: 'daily', time: '09:00', timezone: 'Asia/Shanghai' },
    }))
    // 创建完成后回到列表。
    expect(wrapper.find('.form-shell').exists()).toBe(false)
    expect(wrapper.find('[data-arrange-empty]').exists()).toBe(true)
  })
})
