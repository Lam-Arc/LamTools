import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DirectCallView from '../src/components/DirectCallView.vue'

const models = [
  {
    model_record_id: 'text-model',
    model_id: 'gpt-test',
    display_name: 'GPT Test',
    provider_id: 'openai',
    provider_name: 'OpenAI',
    output_type: 'text',
    capability: 'text',
    context_window: 128000,
    max_output_tokens: 4096,
    temperature: 0.7,
    thinking_supported: false,
    pricing: {},
    has_api_key: true,
    notes: '',
  },
  {
    model_record_id: 'image-model',
    model_id: 'img-test',
    display_name: 'Image Test',
    provider_id: 'openai',
    provider_name: 'OpenAI',
    output_type: 'image',
    capability: 'text',
    context_window: 0,
    max_output_tokens: 0,
    temperature: 0,
    thinking_supported: false,
    pricing: {},
    has_api_key: true,
    notes: '',
  },
]

function finishedCall(overrides: Record<string, unknown> = {}) {
  return {
    id: 'call-1',
    model_record_id: 'text-model',
    model_id: 'gpt-test',
    display_name: 'GPT Test',
    provider_id: 'openai',
    provider_name: 'OpenAI',
    output_type: 'text',
    status: 'completed',
    prompts: ['你好'],
    system: '',
    params: {},
    results: [{
      index: 0,
      prompt: '你好',
      status: 'ok',
      text: '你好，我是模型',
      files: [],
      error: '',
      usage: { total_tokens: 12 },
      duration_ms: 900,
    }],
    error: '',
    created_at: '2026-11-09T10:00:00',
    started_at: '2026-11-09T10:00:00',
    finished_at: '2026-11-09T10:00:01',
    finished: true,
    ...overrides,
  }
}

function makeRpc(options: { call?: Record<string, unknown>; noKey?: boolean; imagegen?: boolean } = {}) {
  const call = options.call || finishedCall()
  const listModels = options.noKey
    ? models.map(model => ({ ...model, has_api_key: false }))
    : models
  return vi.fn(async (method: string, params?: Record<string, unknown>) => {
    if (method === 'direct.catalog') {
      return {
        models: listModels,
        outputs: ['text', 'image', 'video', 'audio'],
        imagegen: { configured: Boolean(options.imagegen), model: options.imagegen ? 'gpt-image-1' : '' },
      }
    }
    if (method === 'direct.list') return { calls: [], total: 0, offset: params?.offset || 0 }
    if (method === 'direct.run') return { call }
    if (method === 'direct.get') return { call }
    if (method === 'direct.retry') return { call }
    if (method === 'direct.save') return { artifacts: [{ artifact_id: 'a1' }] }
    if (method === 'direct.import_imagegen') return { model_record_id: 'image-model', created: true }
    return {}
  })
}

beforeEach(() => {
  window.localStorage.clear()
})

describe('DirectCallView', () => {
  it('lists models grouped by output type and defaults to the first one', async () => {
    const rpc = makeRpc()
    const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'p1' } })
    await flushPromises()

    const entries = wrapper.findAll('[data-direct-model]')
    expect(entries.map(entry => entry.attributes('data-direct-model'))).toEqual(['text-model', 'image-model'])
    expect(wrapper.text()).toContain('调用台')
    expect(wrapper.text()).toContain('将执行 0 条')
  })

  it('switches the input form with the selected output type', async () => {
    const wrapper = mount(DirectCallView, { props: { requestRpc: makeRpc(), projectId: 'p1' } })
    await flushPromises()

    await wrapper.get('[data-direct-model="image-model"]').trigger('click')
    expect(wrapper.text()).toContain('尺寸')
    expect(wrapper.text()).toContain('张数')
    expect(wrapper.text()).not.toContain('系统提示与采样参数')
  })

  it('submits one prompt per non-empty line with the selected model', async () => {
    const rpc = makeRpc()
    const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'p1' } })
    await flushPromises()

    await wrapper.get('[data-direct-input]').setValue('第一条\n\n第二条 ')
    expect(wrapper.text()).toContain('将执行 2 条')

    await wrapper.get('[data-direct-run]').trigger('click')
    await flushPromises()

    const runCall = rpc.mock.calls.find(([method]) => method === 'direct.run')
    expect(runCall).toBeTruthy()
    expect(runCall?.[1]).toMatchObject({
      model_ref: 'text-model',
      prompts: ['第一条', '第二条'],
      project_id: 'p1',
    })
  })

  it('renders a finished result and can save it to the library', async () => {
    const rpc = makeRpc()
    const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'p1' } })
    await flushPromises()

    await wrapper.get('[data-direct-input]').setValue('你好')
    await wrapper.get('[data-direct-run]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('你好，我是模型')
    expect(wrapper.text()).toContain('12 tokens')

    await wrapper.get('[data-direct-save]').trigger('click')
    await flushPromises()

    const saveCall = rpc.mock.calls.find(([method]) => method === 'direct.save')
    expect(saveCall?.[1]).toMatchObject({ call_id: 'call-1', project_id: 'p1' })
    expect(wrapper.text()).toContain('已保存 1 份到资料库')
  })

  it('shows an empty state when no model is configured', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'direct.catalog') return { models: [], outputs: [], imagegen: { configured: false } }
      return { calls: [] }
    })
    const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'p1' } })
    await flushPromises()

    expect(wrapper.text()).toContain('还没有可用模型')
    expect(wrapper.find('[data-direct-run]').exists()).toBe(false)
  })

  it('blocks running when the provider has no key', async () => {
    const wrapper = mount(DirectCallView, { props: { requestRpc: makeRpc({ noKey: true }), projectId: 'p1' } })
    await flushPromises()

    await wrapper.get('[data-direct-input]').setValue('你好')
    expect(wrapper.text()).toContain('还没有密钥')
    expect(wrapper.get('[data-direct-run]').attributes('disabled')).toBeDefined()
  })

  it('filters history by output type', async () => {
    const rpc = makeRpc()
    const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'p1' } })
    await flushPromises()

    const filters = wrapper.findAll('.dc-history-filters button')
    const imageFilter = filters.find(button => button.text() === '图片')
    await imageFilter?.trigger('click')
    await flushPromises()

    const listCalls = rpc.mock.calls.filter(([method]) => method === 'direct.list')
    expect(listCalls.at(-1)?.[1]).toMatchObject({ output_type: 'image', offset: 0 })
  })

  it('retries a single failed result', async () => {
    const failed = finishedCall({
      results: [{
        index: 0,
        prompt: '你好',
        status: 'error',
        text: '',
        files: [],
        error: '供应商返回 500',
        usage: {},
        duration_ms: 300,
      }],
    })
    const rpc = makeRpc({ call: failed })
    const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'p1' } })
    await flushPromises()

    await wrapper.get('[data-direct-input]').setValue('你好')
    await wrapper.get('[data-direct-run]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-direct-retry]').trigger('click')
    await flushPromises()

    const retryCall = rpc.mock.calls.find(([method]) => method === 'direct.retry')
    expect(retryCall?.[1]).toMatchObject({ call_id: 'call-1', index: 0, project_id: 'p1' })
  })

  it('imports the imagegen model when the tool is configured', async () => {
    const rpc = makeRpc({ imagegen: true })
    const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'p1' } })
    await flushPromises()

    // 已有图片模型时左栏不显示导入；把图片模型藏掉模拟“只有文本模型”的常见状态。
    expect(wrapper.find('[data-direct-import-imagegen]').exists()).toBe(false)

    const onlyText = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'direct.catalog') {
        return {
          models: [models[0]],
          outputs: ['text', 'image', 'video', 'audio'],
          imagegen: { configured: true, model: 'gpt-image-1' },
        }
      }
      if (method === 'direct.list') return { calls: [], total: 0, offset: params?.offset || 0 }
      if (method === 'direct.import_imagegen') return { model_record_id: 'image-model', created: true }
      return {}
    })
    const second = mount(DirectCallView, { props: { requestRpc: onlyText, projectId: 'p1' } })
    await flushPromises()

    await second.get('[data-direct-import-imagegen]').trigger('click')
    await flushPromises()

    expect(onlyText.mock.calls.some(([method]) => method === 'direct.import_imagegen')).toBe(true)
  })

  it('remembers sampling parameters per model', async () => {
    const rpc = makeRpc()
    const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'p1' } })
    await flushPromises()

    await wrapper.get('.dc-advanced summary').trigger('click')
    const temperature = wrapper.findAll('.dc-advanced input')[0]
    await temperature.setValue('0.3')
    await wrapper.get('[data-direct-input]').setValue('你好')
    await wrapper.get('[data-direct-run]').trigger('click')
    await flushPromises()

    const stored = JSON.parse(window.localStorage.getItem('lamtools.direct.params') || '{}')
    expect(stored['text-model']).toMatchObject({ temperature: 0.3 })

    await wrapper.get('[data-direct-model="image-model"]').trigger('click')
    await wrapper.get('[data-direct-model="text-model"]').trigger('click')
    await flushPromises()

    expect((wrapper.findAll('.dc-advanced input')[0].element as HTMLInputElement).value).toBe('0.3')
  })
})
