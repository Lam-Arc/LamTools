import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { selectChatMessages, selectCoreWorkbenchMessages, type CoreAppSnapshot, type TransportMessage } from '@lamtools/ui'
import type { LocalDatabase } from '../src/storage/Database'
import { createLocalRepository, type LocalState } from '../src/storage'
import { MemorySecureStorage } from '../src/native/secureStorage'
import { createStandaloneProjectClient } from '../src/standalone/StandaloneProjectClient'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { StandaloneExtensionsStore } from '../src/standalone/StandaloneExtensionsStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'
import { StandaloneTransport, type StudyCall } from '../src/standalone/StandaloneTransport'

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

/**
 * A stand-in for the native Study runtime.
 *
 * Store semantics are covered by the Rust contract tests; these tests only
 * assert what the transport sends across the boundary and how it surfaces
 * failures.
 */
function fakeStudy(overrides: Record<string, (params: Record<string, unknown>) => unknown> = {}) {
  const calls: Array<{
    method: string
    params: Record<string, unknown>
    sessionMetadata?: Record<string, unknown>
    sessionTargets?: Record<string, unknown>
    provider?: unknown
  }> = []
  let primarySession = ''
  const call = vi.fn(async (input: Parameters<StudyCall>[0]) => {
    calls.push(input as (typeof calls)[number])
    const override = overrides[input.method]
    if (override) return override(input.params || {})
    if (input.method === 'study.get') {
      return { revision: 4, total: 1, courses: [{ id: 'course-1', name: '线性代数' }] }
    }
    if (input.method === 'study.context') {
      return {
        instructions: 'STUDY SYSTEM PROMPT',
        request_local_late_context: '[Study latest context]{"selected_node_id":"node-1"}',
      }
    }
    if (input.method === 'study.current') {
      return { current: { id: 'node-1', name: '矩阵' } }
    }
    if (input.method === 'study.binding.primary') {
      return { binding: primarySession ? { session_id: primarySession } : null }
    }
    if (input.method === 'study.binding.ensure') {
      if (input.params?.kind === 'map') primarySession = String(input.params?.session_id || '')
      return { id: 'binding-1', created: true, session_id: input.params?.session_id }
    }
    if (input.method === 'study.text') {
      return { mark: { id: input.params?.id, translate: '跑；运行' } }
    }
    return {}
  }) as unknown as StudyCall
  return { call, calls }
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('StandaloneTransport', () => {
  it('keeps provider execution behind the embedded Rust core', () => {
    const source = readFileSync(new URL('../src/standalone/StandaloneTransport.ts', import.meta.url), 'utf8')
    expect(source).toContain('runEmbeddedSundayTurn')
    expect(source).not.toMatch(/chat\/completions|CapacitorHttp|postModelJson|fetch\s*\(/)
  })

  it('updates an existing standalone model by its record id', async () => {
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test',
      api_type: 'openai',
      base_url: 'https://model.invalid/v1',
      api_key: 'secret',
      models: [{ model_id: 'old-model', display_name: 'Old Model' }],
    })
    const before = await config.handleRpc('config.models.list', {})
    const recordId = String((before?.models as Array<{ id: string }>)[0]?.id || '')

    await config.handleRpc('config.models.upsert', {
      model_record_id: recordId,
      provider_id: 'test',
      model_id: 'new-model',
      display_name: 'New Model',
    })

    const after = await config.handleRpc('config.models.list', {})
    expect(after?.models).toEqual([expect.objectContaining({
      id: recordId,
      model_id: 'new-model',
      display_name: 'New Model',
    })])
  })

  it('persists effective global and project Sub Agent policy', async () => {
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    const builtin = await config.handleRpc('config.subagent.guide.get', { scope: 'global' })
    expect(builtin).toEqual(expect.objectContaining({ is_builtin: true }))
    await config.handleRpc('config.subagent.guide.set', {
      scope: 'global', content: '全局委派说明',
    })
    await config.handleRpc('config.subagent.settings.set', {
      scope: 'global', settings: { delegation_strategy: 'forbidden' },
    })
    expect(await config.subAgentRuntime('project-1')).toEqual({
      enabled: false, guide: '全局委派说明',
    })

    await config.handleRpc('config.subagent.settings.set', {
      scope: 'project', work_root: 'mobile://project-1', settings: { delegation_strategy: 'medium' },
    })
    await config.handleRpc('config.subagent.guide.set', {
      scope: 'project', work_root: 'mobile://project-1', content: '项目委派说明',
    })
    expect(await config.subAgentRuntime('project-1')).toEqual({
      enabled: true, guide: '项目委派说明',
    })
  })

  it('creates local projects and completes a direct model turn without an account', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test',
      api_type: 'openai',
      base_url: 'https://model.invalid/v1',
      api_key: 'secret',
      models: [{
        model_id: 'chat-model',
        display_name: 'Chat Model',
        thinking_supported: true,
        thinking_budget: 4096,
      }],
    })
    const runAgent = vi.fn(async () => ({
      text: '本地独立回复',
      reasoning: '先分析问题',
      runtimeModelId: 'chat-model',
      toolRounds: 0,
      providerState: { protocol: 'openai-chat-completions', model: 'chat-model' },
    }))

    const projectClient = createStandaloneProjectClient(repository)
    const created = await projectClient.create({ name: '手机项目', work_root: '' })
    const transport = new StandaloneTransport(repository, config, runAgent)
    const snapshots: CoreAppSnapshot[] = []
    transport.subscribe((message: TransportMessage) => {
      if (message.method === 'thread/snapshot' && message.params) snapshots.push(message.params as unknown as CoreAppSnapshot)
    })

    await transport.connect()
    await transport.request({ method: 'initialize', params: {} })
    await transport.request({
      method: 'turn/start',
      params: {
        thread_id: created.session.id,
        input: [{ type: 'text', text: '你好' }],
        reasoning_level: 'high',
        max_tokens: 1234,
      },
    })

    await vi.waitFor(() => expect(snapshots.at(-1)?.status).toBe('completed'))
    expect(runAgent).toHaveBeenCalledWith(expect.objectContaining({
      projectId: created.project.id,
      modelRecordId: 'test:chat-model',
      history: [expect.objectContaining({ role: 'user', content: '你好' })],
      reasoningLevel: 'high',
      thinkingBudget: 4096,
      maxOutputTokens: 1234,
      models: [expect.objectContaining({
        id: 'test:chat-model',
        displayName: 'Chat Model',
        apiKey: 'secret',
      })],
    }))
    const resumed = await transport.request<Record<string, unknown>>({
      method: 'thread/resume',
      params: { thread_id: created.session.id },
    })
    const snapshot = resumed.snapshot as CoreAppSnapshot
    const assistant = Object.values(snapshot.core?.items || {}).find((item) => item.payload?.type === 'agentMessage')
    const user = Object.values(snapshot.core?.items || {}).find((item) => item.payload?.type === 'userMessage')
    expect(assistant?.payload?.content).toBe('本地独立回复')
    expect(assistant?.payload?.provider_state).toEqual({ protocol: 'openai-chat-completions', model: 'chat-model' })
    expect(user?.payload?.content).toEqual([{ type: 'text', text: '你好' }])
    expect(selectChatMessages(snapshot)[0]).toEqual(expect.objectContaining({ role: 'user', content: '你好' }))
    expect(Object.values(snapshot.core?.items || {})).toContainEqual(expect.objectContaining({
      kind: 'thinking', content: '先分析问题',
    }))
    expect(Object.values(snapshot.core?.turns || {})[0]?.runtime_snapshot).toEqual({
      model_id: 'chat-model',
      model_record_id: 'test:chat-model',
      reasoning_level: 'high',
      thinking_budget: 4096,
      max_tokens: 1234,
      permission_preset: 'ask',
      session_approved_tools: [],
    })
    expect(await repository.listProjects()).toHaveLength(1)
    expect(await repository.listSessions(created.project.id)).toHaveLength(1)
  })

  it.each([
    { label: 'a thinking model uses the desktop default', thinking_supported: true, expected: 'max' },
    { label: 'a model without thinking support stays off', thinking_supported: false, expected: 'off' },
  ])('$label when the caller chose nothing', async ({ thinking_supported, expected }) => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test',
      api_type: 'openai',
      base_url: 'https://model.invalid/v1',
      api_key: 'secret',
      models: [{ model_id: 'level-model', display_name: 'Level Model', thinking_supported }],
    })
    const runAgent = vi.fn(async () => ({
      text: 'ok', runtimeModelId: 'level-model', toolRounds: 0,
    }))
    const projectClient = createStandaloneProjectClient(repository)
    const created = await projectClient.create({ name: '手机项目', work_root: '' })
    const transport = new StandaloneTransport(repository, config, runAgent)
    await transport.connect()
    await transport.request({ method: 'initialize', params: {} })

    await transport.request({
      method: 'turn/start',
      params: { thread_id: created.session.id, input: [{ type: 'text', text: '你好' }] },
    })

    await vi.waitFor(() => expect(runAgent).toHaveBeenCalled())
    // Mobile has no level picker, so it must follow the desktop resolution
    // instead of silently disabling thinking on every turn.
    expect(runAgent).toHaveBeenCalledWith(expect.objectContaining({ reasoningLevel: expected }))
  })

  it('forwards the 设置 → 生图 configuration to the native runtime', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'image-model', display_name: 'Image Model' }],
    })
    // The shared image generation panel writes this namespace.
    await config.handleRpc('settings.update', {
      namespace: 'core.imagegen',
      value: { enabled: true, api_url: 'https://images.invalid/v1', api_key: 'img-key', model: 'dall-e' },
    })
    const runAgent = vi.fn(async () => ({
      text: 'ok', runtimeModelId: 'image-model', toolRounds: 0,
    }))
    const created = await createStandaloneProjectClient(repository).create({ name: '生图项目', work_root: '' })
    const transport = new StandaloneTransport(repository, config, runAgent)
    await transport.connect()
    await transport.request({ method: 'initialize', params: {} })

    await transport.request({
      method: 'turn/start',
      params: { thread_id: created.session.id, input: [{ type: 'text', text: '画一张图' }] },
    })

    await vi.waitFor(() => expect(runAgent).toHaveBeenCalled())
    // Without this the Rust tool can never be configured, so it would stay
    // hidden from the model no matter what the panel says.
    expect(runAgent).toHaveBeenCalledWith(expect.objectContaining({
      imagegenConfig: expect.objectContaining({
        enabled: true,
        api_url: 'https://images.invalid/v1',
        model: 'dall-e',
      }),
    }))
  })

  it('keeps each tool round visible instead of letting the next round replace it', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'stream-model', display_name: 'Stream Model' }],
    })
    const created = await createStandaloneProjectClient(repository).create({ name: '流式项目', work_root: '' })
    const result = deferred<{ text: string; runtimeModelId: string; toolRounds: number }>()
    const runAgent = vi.fn(() => result.promise)
    let onStream: ((payload: unknown) => void) | undefined
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, undefined, undefined, undefined,
      async handler => { onStream = handler; return vi.fn() },
    )
    const snapshots: CoreAppSnapshot[] = []
    transport.subscribe((message: TransportMessage) => {
      if (message.method === 'thread/snapshot' && message.params) snapshots.push(message.params as unknown as CoreAppSnapshot)
    })

    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: '看一下文件' }],
    } })
    await vi.waitFor(() => expect(onStream).toBeTypeOf('function'))
    const { turn_id: turnId } = (await vi.waitFor(() => {
      const turn = Object.values(snapshots.at(-1)?.core?.turns || {})[0]
      expect(turn?.turn_id).toBeTruthy()
      return turn!
    }))
    const items = () => snapshots.at(-1)?.core?.items || {}
    const order = () => snapshots.at(-1)?.core?.item_order || []

    // Round one narrates, thinks, then calls a tool.
    onStream!({ turnId, kind: 'text_delta', delta: '我先读一下文件' })
    onStream!({ turnId, kind: 'reasoning_delta', delta: '需要先确认内容' })
    await vi.waitFor(() => {
      expect(items()[`${turnId}:assistant`]?.payload?.content).toBe('我先读一下文件')
      expect(items()[`${turnId}:reasoning`]?.content).toBe('需要先确认内容')
    })
    onStream!({ turnId, kind: 'tool_call', data: {
      id: 'call-1', name: 'read_text_file', arguments: '{"path":"a.txt"}',
    } })
    await vi.waitFor(() => {
      const tool = items()[`${turnId}:tool:call-1`]
      expect(tool?.tool_name).toBe('read_text_file')
      expect(tool?.status).toBe('running')
      expect(tool?.kind).toBe('tool_call')
      // The shared card reads the display fields from the payload, and a
      // structured preview lets it show the target instead of raw JSON.
      expect(tool?.payload?.type).toBe('dynamicToolCall')
      expect(tool?.payload?.arguments).toEqual({ path: 'a.txt' })
    })
    onStream!({ turnId, kind: 'tool_result', data: {
      id: 'call-1', name: 'read_text_file', ok: true, preview: '文件内容',
    } })
    await vi.waitFor(() => {
      expect(items()[`${turnId}:tool:call-1`]?.status).toBe('completed')
      expect(items()[`${turnId}:tool:call-1`]?.payload?.tool_result).toBe('文件内容')
    })

    // The next round must not erase what the user already read.
    onStream!({ turnId, kind: 'reset' })
    const afterReset = items()
    const narration = Object.values(afterReset).find(item => item.payload?.final_response === false)
    expect(narration?.content).toBe('我先读一下文件')
    expect(Object.values(afterReset).some(
      item => item.type === 'reasoning' && item.content === '需要先确认内容' && item.status === 'completed',
    )).toBe(true)
    expect(afterReset[`${turnId}:assistant`]?.payload?.content).toBe('')
    expect(afterReset[`${turnId}:reasoning`]).toBeUndefined()
    expect(afterReset[`${turnId}:tool:call-1`]?.status).toBe('completed')

    // Round two answers, and the archived process stays ahead of the answer.
    onStream!({ turnId, kind: 'text_delta', delta: '文件里写的是 x' })
    result.resolve({ text: '文件里写的是 x', runtimeModelId: 'stream-model', toolRounds: 1 })

    await vi.waitFor(() => expect(snapshots.at(-1)?.status).toBe('completed'))
    expect(items()[`${turnId}:assistant`]?.payload?.content).toBe('文件里写的是 x')
    const finalOrder = order()
    expect(finalOrder.indexOf(`${turnId}:tool:call-1`)).toBeGreaterThanOrEqual(0)
    expect(finalOrder.indexOf(`${turnId}:tool:call-1`)).toBeLessThan(finalOrder.indexOf(`${turnId}:assistant`))
    expect(finalOrder.indexOf(String(narration?.item_id))).toBeLessThan(finalOrder.indexOf(`${turnId}:assistant`))

    // Proof the shared renderer actually draws the step: the same projection the
    // transcript uses must yield a tool card carrying the result, and the
    // narration must survive next to it.
    const parts = selectCoreWorkbenchMessages(snapshots.at(-1)!)
      .flatMap(message => message.parts || [])
    expect(parts).toEqual(expect.arrayContaining([
      expect.objectContaining({
        partType: 'tool_call',
        toolName: 'read_text_file',
        toolResult: '文件内容',
        status: 'completed',
      }),
      expect.objectContaining({
        partType: 'model_text',
        content: '我先读一下文件',
      }),
    ]))
  })

  it('shows bounded native text and reasoning deltas, resets provisional output, then trusts the final result', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'stream-model', display_name: 'Stream Model' }],
    })
    const created = await createStandaloneProjectClient(repository).create({ name: '流式项目', work_root: '' })
    const result = deferred<{ text: string; runtimeModelId: string; toolRounds: number }>()
    const runAgent = vi.fn(() => result.promise)
    let onStream: ((payload: unknown) => void) | undefined
    const unlisten = vi.fn()
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, undefined, undefined, undefined,
      async handler => { onStream = handler; return unlisten },
    )
    const snapshots: CoreAppSnapshot[] = []
    transport.subscribe((message: TransportMessage) => {
      if (message.method === 'thread/snapshot' && message.params) snapshots.push(message.params as unknown as CoreAppSnapshot)
    })

    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: '输出内容' }],
    } })
    await vi.waitFor(() => expect(onStream).toBeTypeOf('function'))
    const { turn_id: turnId } = (await vi.waitFor(() => {
      const turn = Object.values(snapshots.at(-1)?.core?.turns || {})[0]
      expect(turn?.turn_id).toBeTruthy()
      return turn!
    }))
    const initialAssistantSeq = snapshots.at(-1)?.core?.items?.[`${turnId}:assistant`]?.seq
    onStream!({ turnId, kind: 'text_delta', delta: '临时回答' })
    onStream!({ turnId, kind: 'reasoning_delta', delta: '临时思考' })
    await vi.waitFor(() => {
      const snapshot = snapshots.at(-1)!
      expect(snapshot.status).toBe('running')
      expect(snapshot.core?.items?.[`${turnId}:assistant`]?.payload?.content).toBe('临时回答')
      expect(snapshot.core?.items?.[`${turnId}:reasoning`]?.content).toBe('临时思考')
    })

    onStream!({ turnId, kind: 'reset' })
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:assistant`]?.payload?.content).toBe('')
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:assistant`]?.seq).toBe(initialAssistantSeq)
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:reasoning`]).toBeUndefined()
    onStream!({ turnId, kind: 'text_delta', delta: '重试回答' })
    result.resolve({
      text: '最终权威答案', reasoning: '最终权威思考', runtimeModelId: 'stream-model', toolRounds: 0,
    })

    await vi.waitFor(() => expect(snapshots.at(-1)?.status).toBe('completed'))
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:assistant`]?.payload?.content).toBe('最终权威答案')
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:reasoning`]?.content).toBe('最终权威思考')
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:reasoning`]?.seq).toBe(initialAssistantSeq)
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:assistant`]?.seq).toBe(Number(initialAssistantSeq) + 1)
    expect(unlisten).toHaveBeenCalledOnce()
  })

  it('settles streamed reasoning when the native turn fails', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'stream-model', display_name: 'Stream Model' }],
    })
    const created = await createStandaloneProjectClient(repository).create({ name: '失败流式项目', work_root: '' })
    let rejectRun!: (error: Error) => void
    const runAgent = vi.fn(() => new Promise<any>((_resolve, reject) => { rejectRun = reject }))
    let onStage: ((payload: unknown) => void) | undefined
    let onStream: ((payload: unknown) => void) | undefined
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, undefined, undefined,
      async handler => { onStage = handler; return () => {} },
      async handler => { onStream = handler; return () => {} },
    )
    const snapshots: CoreAppSnapshot[] = []
    transport.subscribe((message: TransportMessage) => {
      if (message.method === 'thread/snapshot' && message.params) snapshots.push(message.params as unknown as CoreAppSnapshot)
    })

    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: '思考后失败' }],
    } })
    const turnId = String(started.turn_id)
    await vi.waitFor(() => expect(onStage).toBeTypeOf('function'))
    onStage!({ turnId, stage: 'http_streaming' })
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:assistant`]?.metadata)
      .toEqual(expect.objectContaining({ mobile_turn_progress: expect.objectContaining({ label: '正在生成回复' }) }))
    await vi.waitFor(() => expect(onStream).toBeTypeOf('function'))
    onStream!({ turnId, kind: 'reasoning_delta', delta: '已收到的思考' })
    await vi.waitFor(() => expect(snapshots.at(-1)?.core?.items?.[`${turnId}:reasoning`]?.status).toBe('running'))

    rejectRun(new Error('native turn failed'))
    await vi.waitFor(() => expect(snapshots.at(-1)?.status).toBe('failed'))
    expect(snapshots.at(-1)?.core?.items?.[`${turnId}:reasoning`]).toEqual(expect.objectContaining({
      content: '已收到的思考', status: 'failed',
    }))
    expect(Object.values(snapshots.at(-1)?.core?.items || {}).some(item => item.status === 'running')).toBe(false)
  })

  it('persists project-scoped files in standalone mode', async () => {
    const database = new MemoryDatabase()
    const repository = createLocalRepository(database)
    const projectClient = createStandaloneProjectClient(repository)
    const created = await projectClient.create({ name: '手机项目', work_root: '' })
    await expect(projectClient.writeFile(created.project.id, 'a.txt', 'x'))
      .resolves.toEqual({ path: 'a.txt', content: 'x' })
    await expect(projectClient.readFile(created.project.id, 'a.txt'))
      .resolves.toEqual({ path: 'a.txt', content: 'x' })
    await repository.close()
    const restored = createStandaloneProjectClient(createLocalRepository(database))
    await expect(restored.list()).resolves.toEqual([expect.objectContaining({ id: created.project.id })])
    await expect(restored.readFile(created.project.id, 'a.txt')).resolves.toEqual({ path: 'a.txt', content: 'x' })
  })

  it('delegates tool-capable turns to the embedded Rust core', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '工具项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'tool-model', display_name: 'Tool Model' }],
    })
    const runAgent = vi.fn(async () => ({
      text: '文件已创建。', runtimeModelId: 'test:tool-model', toolRounds: 1,
    }))
    const transport = new StandaloneTransport(repository, config, runAgent)

    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: '创建你好.txt' }],
    } })

    await vi.waitFor(() => expect(runAgent).toHaveBeenCalledWith(expect.objectContaining({
      projectId: created.project.id,
      modelRecordId: 'test:tool-model',
    })))
    await vi.waitFor(async () => {
      const snapshot = await repository.loadThreadSnapshot(created.session.id)
      expect(snapshot?.status).toBe('completed')
    })
  })

  it('reuses the durable Rust runtime history on the next turn', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '长会话项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'history-model', display_name: 'History Model', context_window: 32768 }],
    })
    const runAgent = vi.fn(async (input: any) => ({
      text: runAgent.mock.calls.length === 1 ? '第一轮' : '第二轮',
      runtimeModelId: 'history-model',
      toolRounds: 0,
      runtimeHistory: [
        ...input.history,
        { role: 'assistant', content: runAgent.mock.calls.length === 1 ? '第一轮' : '第二轮' },
      ],
      compaction: runAgent.mock.calls.length === 1
        ? { originalTokens: 40000, compactedTokens: 18000, summarizedMessages: 20 }
        : null,
    }))
    const transport = new StandaloneTransport(repository, config, runAgent)

    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: '第一条' }],
    } })
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('completed')
    })
    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: '第二条' }],
    } })
    await vi.waitFor(() => expect(runAgent).toHaveBeenCalledTimes(2))

    expect(runAgent.mock.calls[1][0]).toEqual(expect.objectContaining({
      history: [
        { role: 'user', content: '第一条' },
        { role: 'assistant', content: '第一轮' },
        { role: 'user', content: '第二条' },
      ],
    }))
    const sessions = await repository.listSessions()
    expect(sessions[0]?.metadata).toEqual(expect.objectContaining({
      rust_compaction: { originalTokens: 40000, compactedTokens: 18000, summarizedMessages: 20 },
    }))
  })

  it('does not replay late runtime history from a turn cancelled during metadata persistence', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '历史 Stop 项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'history-model', display_name: 'History Model' }],
    })
    const entered = deferred<void>()
    const release = deferred<void>()
    const originalUpdate = repository.updateLocalSession.bind(repository)
    vi.spyOn(repository, 'updateLocalSession').mockImplementation(async (...args) => {
      if (args[1].metadata?.rust_runtime_history) {
        entered.resolve()
        await release.promise
      }
      return originalUpdate(...args)
    })
    const runAgent = vi.fn(async (input: any) => ({
      text: runAgent.mock.calls.length === 1 ? 'cancelled answer' : 'next answer',
      runtimeModelId: 'history-model', toolRounds: 0,
      runtimeHistory: [
        ...input.history,
        { role: 'assistant', content: runAgent.mock.calls.length === 1 ? 'cancelled answer' : 'next answer' },
      ],
    }))
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, vi.fn(async () => true),
    )

    const first = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'first question' }],
    } })
    await entered.promise
    await transport.request({ method: 'turn/interrupt', params: { thread_id: created.session.id } })
    release.resolve()
    await vi.waitFor(async () => {
      const session = (await repository.listSessions()).find(item => item.id === created.session.id)
      expect(session?.metadata?.rust_runtime_history_turn_id).toBe(first.turn_id)
    })
    expect((await repository.loadThreadSnapshot(created.session.id))?.core?.turns?.[String(first.turn_id)]?.status)
      .toBe('cancelled')

    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'next question' }],
    } })
    await vi.waitFor(() => expect(runAgent).toHaveBeenCalledTimes(2))
    expect(runAgent.mock.calls[1][0].history).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'user', content: 'next question' },
    ])
  })

  it.each([undefined, 'study:study'])('retains mode %s and skill switches across a tool approval', async (activeMode) => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '审批项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'tool-model', display_name: 'Tool Model' }],
    })
    const runAgent = vi.fn(async (input: any) => ({
      status: 'approval_required' as const,
      request: {
        requestId: `${input.turnId}:approval:0:0:call-1`,
        toolCall: { id: 'call-1', name: 'write_text_file', arguments: { path: 'a.txt' } },
        message: "Allow Sunday Agent to run 'write_text_file'?",
      },
      continuation: {
        turnId: input.turnId,
        modelRecordId: input.modelRecordId,
        messages: [], capabilities: {}, options: {}, toolRounds: 0,
        pendingCalls: [], nextCallIndex: 0,
      },
    }))
    const resumedResult = deferred<any>()
    const resumeAgent = vi.fn(() => resumedResult.promise)
    let onStream: ((payload: unknown) => void) | undefined
    const extensions = new StandaloneExtensionsStore(new MemoryStandaloneStateStorage({ disabledPlugins: [], disabledSkills: ['teach'] }))
    const transport = new StandaloneTransport(
      repository, config, runAgent, extensions, resumeAgent,
      fakeStudy().call, undefined, undefined, undefined,
      async handler => { onStream = handler; return () => {} },
    )
    const snapshots: CoreAppSnapshot[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot' && message.params) snapshots.push(message.params as unknown as CoreAppSnapshot)
    })

    const start = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: '创建 a.txt' }],
      permission_preset: 'ask',
      active_mode: activeMode,
    } })
    const turnId = String(start.turn_id)
    const requestId = `${turnId}:approval:0:0:call-1`
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('waiting')
    })
    const waiting = await repository.loadThreadSnapshot(created.session.id)
    const initialAssistantSeq = waiting?.core?.items?.[`${turnId}:assistant`]?.seq
    expect(waiting?.core?.requests?.[requestId]).toEqual(expect.objectContaining({
      status: 'open',
      continuation: expect.objectContaining({ turnId }),
    }))
    expect(selectChatMessages(waiting!)).toEqual(expect.arrayContaining([
      expect.objectContaining({
        role: 'assistant',
        parts: expect.arrayContaining([expect.objectContaining({ type: 'serverRequest', request_id: requestId })]),
      }),
    ]))

    onStream = undefined
    await transport.request({ method: 'approval/respond', params: {
      thread_id: created.session.id,
      request_id: requestId,
      decision: 'approve_once',
    } })
    await vi.waitFor(() => expect(onStream).toBeTypeOf('function'))
    onStream!({ turnId, kind: 'reasoning_delta', delta: '续跑思考' })
    await vi.waitFor(() => {
      const live = snapshots.at(-1)?.core?.items?.[`${turnId}:reasoning`]
      expect(live?.content).toBe('续跑思考')
      expect(live?.seq).toBe(snapshots.at(-1)?.core?.items?.[`${turnId}:assistant`]?.seq)
    })
    resumedResult.resolve({
      status: 'completed',
      result: {
        text: '文件已创建。', reasoning: '最终续跑思考', runtimeModelId: 'tool-model', toolRounds: 1,
        sessionApprovedTools: [],
      },
    })
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('completed')
    })
    expect(resumeAgent).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: created.session.id,
      requestId,
      decision: 'approve_once',
      projectId: created.project.id,
      models: [expect.objectContaining({ id: 'test:tool-model', apiKey: 'secret' })],
      study: { enabled: activeMode === 'study:study' },
      disabledSkillNames: ['teach'],
    }))
    const completed = await repository.loadThreadSnapshot(created.session.id)
    const assistant = completed?.core?.items?.[`${turnId}:assistant`]
    const reasoning = completed?.core?.items?.[`${turnId}:reasoning`]
    expect(reasoning?.content).toBe('最终续跑思考')
    expect(reasoning?.seq).toBe(initialAssistantSeq)
    expect(assistant?.seq).toBe(Number(initialAssistantSeq) + 1)
    expect(completed?.core?.item_order?.indexOf(`${turnId}:reasoning`))
      .toBeLessThan(completed?.core?.item_order?.indexOf(`${turnId}:assistant`) ?? -1)
  })

  it('keeps Stop authoritative when a completed turn is waiting on session persistence', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: 'Stop 项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'stop-model', display_name: 'Stop Model' }],
    })
    const entered = deferred<void>()
    const release = deferred<void>()
    const originalUpdate = repository.updateLocalSession.bind(repository)
    vi.spyOn(repository, 'updateLocalSession').mockImplementation(async (...args) => {
      entered.resolve()
      await release.promise
      return originalUpdate(...args)
    })
    const transport = new StandaloneTransport(repository, config, vi.fn(async () => ({
      text: 'late answer', runtimeModelId: 'stop-model', toolRounds: 0,
      sessionApprovedTools: ['write_text_file'],
    })), undefined, undefined, undefined, vi.fn(async () => true))
    const observed: string[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(String(message.params?.status))
    })

    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await entered.promise
    await transport.request({ method: 'turn/interrupt', params: { thread_id: created.session.id } })
    release.resolve()
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('cancelled')
    })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('cancelled')
    expect(observed).not.toContain('completed')
  })

  it('does not start a turn after Stop while model lookup is pending', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '开始 Stop 项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'stop-model', display_name: 'Stop Model' }],
    })
    const entered = deferred<void>()
    const release = deferred<void>()
    const originalActiveModel = config.activeModel.bind(config)
    vi.spyOn(config, 'activeModel').mockImplementation(async (...args) => {
      entered.resolve()
      await release.promise
      return originalActiveModel(...args)
    })
    const runAgent = vi.fn(async () => ({ text: 'late answer', runtimeModelId: 'stop-model', toolRounds: 0 }))
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, vi.fn(async () => true),
    )

    const start = transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await entered.promise
    await transport.request({ method: 'turn/interrupt', params: { thread_id: created.session.id } })
    release.resolve()
    await expect(start).rejects.toThrow('操作已取消')
    expect(runAgent).not.toHaveBeenCalled()
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('cancelled')
  })

  it('recovers a running snapshot after WebView reload without cancelling a live connection', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '重载项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'reload-model', display_name: 'Reload Model' }],
    })
    const entered = deferred<void>()
    const never = deferred<never>()
    const runAgent = vi.fn(async () => { entered.resolve(); return await never.promise })
    const liveCancel = vi.fn(async () => true)
    const live = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, liveCancel,
    )
    const started = await live.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await entered.promise
    await live.connect()
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('running')
    expect(liveCancel).not.toHaveBeenCalled()

    const orphanCancel = vi.fn(async () => true)
    const reloaded = new StandaloneTransport(
      repository, config, undefined, undefined, undefined, undefined, orphanCancel,
    )
    const resumed = await reloaded.request<{ snapshot: CoreAppSnapshot }>({
      method: 'thread/resume', params: { thread_id: created.session.id },
    })
    expect(orphanCancel).toHaveBeenCalledWith(started.turn_id)
    expect(resumed.snapshot.status).toBe('cancelled')
    expect(resumed.snapshot.core?.turns?.[String(started.turn_id)]?.status).toBe('cancelled')
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('cancelled')
  })

  it('emits a terminal snapshot when the final save fails', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '保存失败项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'save-model', display_name: 'Save Model' }],
    })
    const originalSave = repository.saveLocalSnapshot.bind(repository)
    vi.spyOn(repository, 'saveLocalSnapshot').mockImplementation(async snapshot => {
      if (snapshot.status === 'completed') throw new Error('disk unavailable')
      await originalSave(snapshot)
    })
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => {})
    const transport = new StandaloneTransport(repository, config, vi.fn(async () => ({
      text: 'answer', runtimeModelId: 'save-model', toolRounds: 0,
    })))
    const observed: CoreAppSnapshot[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(message.params as CoreAppSnapshot)
    })
    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await vi.waitFor(() => expect(observed.some(snapshot => snapshot.status === 'completed')).toBe(true))
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('running')
    expect(errorLog).toHaveBeenCalledWith('Failed to save standalone turn snapshot', expect.any(Error))
    errorLog.mockRestore()
  })

  it('shows live stages in ordinary operation without exposing them to answer or model history', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '跟踪项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'trace-model', display_name: 'Trace Model' }],
    })
    const first = deferred<{ text: string; runtimeModelId: string; toolRounds: number }>()
    const runAgent = vi.fn(async () => runAgent.mock.calls.length === 1
      ? await first.promise
      : { text: 'second answer', runtimeModelId: 'trace-model', toolRounds: 0 })
    let stageHandler: (payload: unknown) => void = () => {}
    const unlisten = vi.fn()
    const listenStage = vi.fn(async (handler: (payload: unknown) => void) => {
      stageHandler = handler
      return unlisten
    })
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, undefined, undefined, listenStage,
    )
    const observed: CoreAppSnapshot[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(message.params as CoreAppSnapshot)
    })
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'first question' }],
    } })
    await vi.waitFor(() => expect(runAgent).toHaveBeenCalledTimes(1))
    stageHandler({ turnId: 'other-turn', stage: 'http_send_start' })
    stageHandler({ turnId: started.turn_id, stage: 'api_key=should-never-appear' })
    stageHandler({ turnId: started.turn_id, stage: 'http_send_start', secret: 'should-never-appear' })
    stageHandler({ turnId: started.turn_id, stage: 'http_request_built' })
    stageHandler({ turnId: started.turn_id, stage: 'http_request_build_error' })
    stageHandler({ turnId: started.turn_id, stage: 'http_waiting_for_headers' })
    stageHandler({ turnId: started.turn_id, stage: 'http_connect_error' })
    stageHandler({ turnId: started.turn_id, stage: 'http_send_timeout' })
    await vi.waitFor(() => expect(observed.some(snapshot =>
      (snapshot.core?.items?.[`${started.turn_id}:assistant`]?.metadata as any)?.mobile_turn_progress?.label === '等待模型响应超时')).toBe(true))
    const liveItem = observed.at(-1)?.core?.items?.[`${started.turn_id}:assistant`]
    expect(String(liveItem?.content || '')).toBe('')
    expect(JSON.stringify(liveItem?.metadata)).not.toContain('should-never-appear')
    expect((liveItem?.metadata as any)?.mobile_turn_progress).toEqual({
      stage: 'http_send_timeout', label: '等待模型响应超时', status: 'running',
    })
    first.resolve({ text: 'first answer', runtimeModelId: 'trace-model', toolRounds: 0 })
    await vi.waitFor(async () => {
      const saved = await repository.loadThreadSnapshot(created.session.id)
      expect(saved?.status).toBe('completed')
      expect(String(saved?.core?.items?.[`${started.turn_id}:assistant`]?.content))
        .toContain('first answer')
    })
    expect(unlisten).toHaveBeenCalled()
    const completed = await repository.loadThreadSnapshot(created.session.id)
    expect(String(completed?.core?.items?.[`${started.turn_id}:assistant`]?.content)).toBe('first answer')
    expect((completed?.core?.items?.[`${started.turn_id}:assistant`]?.metadata as any)?.mobile_turn_progress)
      .toEqual(expect.objectContaining({ status: 'completed', label: '已完成', expires_at: expect.any(Number) }))
    const emissionCount = observed.length
    stageHandler({ turnId: started.turn_id, stage: 'http_send_start' })
    expect(observed).toHaveLength(emissionCount)

    await transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'second question' }],
    } })
    await vi.waitFor(() => expect(runAgent).toHaveBeenCalledTimes(2))
    const history = (runAgent.mock.calls[1]?.[0] as any).history as Array<{ role: string; content: string }>
    expect(history).toContainEqual({ role: 'assistant', content: 'first answer' })
    expect(JSON.stringify(history)).not.toContain('正在发送模型请求')
    expect(JSON.stringify(history)).not.toContain('执行过程')
  })

  it('adds one-shot JS wait markers while native execution is pending and clears them on result', async () => {
    vi.stubEnv('VITE_MOBILE_TRACE_TURNS', '1')
    vi.useFakeTimers()
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '等待标记项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'trace-model', display_name: 'Trace Model' }],
    })
    const result = deferred<{ text: string; runtimeModelId: string; toolRounds: number }>()
    const entered = deferred<void>()
    const runAgent = vi.fn(async () => {
      entered.resolve()
      return await result.promise
    })
    const transport = new StandaloneTransport(repository, config, runAgent)
    const observed: CoreAppSnapshot[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(message.params as CoreAppSnapshot)
    })
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await entered.promise
    const progress = () => (observed.at(-1)?.core?.items?.[`${started.turn_id}:assistant`]?.metadata as any)?.mobile_turn_progress

    await vi.advanceTimersByTimeAsync(34_999)
    expect(progress()?.stage).not.toBe('js_native_wait_35s')
    await vi.advanceTimersByTimeAsync(1)
    expect(progress()?.label).toBe('界面仍在等待原生运行时（35秒）')
    await vi.advanceTimersByTimeAsync(90_000)
    expect(progress()?.label).toBe('界面仍在等待原生运行时（125秒）')

    result.resolve({ text: 'done', runtimeModelId: 'trace-model', toolRounds: 0 })
    await vi.waitFor(() => expect(observed.at(-1)?.status).toBe('completed'))
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(125_000)
    expect(progress()?.status).toBe('completed')
    expect(String(observed.at(-1)?.core?.items?.[`${started.turn_id}:assistant`]?.content)).toBe('done')
  })

  it('clears pending JS wait markers when the native turn is cancelled', async () => {
    vi.stubEnv('VITE_MOBILE_TRACE_TURNS', '1')
    vi.useFakeTimers()
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '取消等待标记项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'trace-model', display_name: 'Trace Model' }],
    })
    const pending = deferred<{ text: string; runtimeModelId: string; toolRounds: number }>()
    const entered = deferred<void>()
    const runAgent = vi.fn(async () => {
      entered.resolve()
      return await pending.promise
    })
    const transport = new StandaloneTransport(repository, config, runAgent, undefined, undefined, undefined,
      async () => true)
    const observed: CoreAppSnapshot[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(message.params as CoreAppSnapshot)
    })
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await entered.promise
    await transport.request({ method: 'turn/interrupt', params: { thread_id: created.session.id } })
    expect(observed.at(-1)?.status).toBe('cancelled')
    expect((observed.at(-1)?.core?.items?.[`${started.turn_id}:assistant`]?.metadata as any)?.mobile_turn_progress)
      .toEqual(expect.objectContaining({ status: 'cancelled', label: '已取消' }))
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(130_000)
    expect(JSON.stringify(observed)).not.toContain('界面仍在等待原生运行时')
    // Keep the mocked native promise handled after the generation is invalidated.
    pending.resolve({ text: 'late result', runtimeModelId: 'trace-model', toolRounds: 0 })
    await Promise.resolve()
    expect(String(observed.at(-1)?.core?.items?.[`${started.turn_id}:assistant`]?.content))
      .not.toContain('late result')
  })

  it('shows model lookup and initial persistence stalls before native execution', async () => {
    vi.stubEnv('VITE_MOBILE_TRACE_TURNS', '1')
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '早期跟踪项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    const model = deferred<Awaited<ReturnType<StandaloneConfigStore['activeModel']>>>()
    vi.spyOn(config, 'activeModel').mockImplementation(async () => await model.promise)
    const observed: CoreAppSnapshot[] = []
    const transport = new StandaloneTransport(repository, config, undefined, undefined, undefined, undefined,
      undefined, undefined, async () => () => {})
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(message.params as CoreAppSnapshot)
    })
    const pending = transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await vi.waitFor(() => expect(observed.some(snapshot => JSON.stringify(snapshot).includes('正在读取当前模型'))).toBe(true))
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('idle')
    model.resolve({ provider: {} as any, model: { id: 'model-1', model_id: 'model-1' } as any, apiKey: '' })
    const initialSave = deferred<void>()
    const originalSave = repository.saveLocalSnapshot.bind(repository)
    vi.spyOn(repository, 'saveLocalSnapshot').mockImplementation(async snapshot => {
      if (snapshot.status === 'running') await initialSave.promise
      await originalSave(snapshot)
    })
    await vi.waitFor(() => expect(observed.some(snapshot => JSON.stringify(snapshot).includes('正在保存请求'))).toBe(true))
    initialSave.resolve()
    await pending
  })

  it('keeps the failure text separate from terminal progress', async () => {
    vi.stubEnv('VITE_MOBILE_TRACE_TURNS', '1')
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '失败跟踪项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'trace-model', display_name: 'Trace Model' }],
    })
    const entered = deferred<void>()
    const release = deferred<void>()
    const runAgent = vi.fn(async () => {
      entered.resolve()
      await release.promise
      throw new Error('model failed')
    })
    let stageHandler: (payload: unknown) => void = () => {}
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, undefined, undefined,
      async handler => { stageHandler = handler; return () => {} },
    )
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'fail' }],
    } })
    await entered.promise
    stageHandler({ turnId: started.turn_id, stage: 'http_transport_error' })
    release.resolve()
    await vi.waitFor(async () => {
      const saved = await repository.loadThreadSnapshot(created.session.id)
      expect(saved?.status).toBe('failed')
      const content = String(saved?.core?.items?.[`${started.turn_id}:assistant`]?.content)
      expect(content).toBe('model failed')
      expect((saved?.core?.items?.[`${started.turn_id}:assistant`]?.metadata as any)?.mobile_turn_progress)
        .toEqual(expect.objectContaining({ status: 'failed', label: '运行失败' }))
    })
  })

  it('continues after stage listener registration stalls and closes a late listener', async () => {
    vi.stubEnv('VITE_MOBILE_TRACE_TURNS', '1')
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '监听超时项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'trace-model', display_name: 'Trace Model' }],
    })
    const registration = deferred<() => void>()
    const unlisten = vi.fn()
    const runAgent = vi.fn(async () => ({ text: 'answer', runtimeModelId: 'trace-model', toolRounds: 0 }))
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, undefined, undefined,
      async () => await registration.promise,
    )
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await vi.waitFor(() => expect(runAgent).toHaveBeenCalledTimes(1), { timeout: 3000 })
    await vi.waitFor(async () => {
      const saved = await repository.loadThreadSnapshot(created.session.id)
      expect(saved?.status).toBe('completed')
      const content = String(saved?.core?.items?.[`${started.turn_id}:assistant`]?.content)
      expect(content).toBe('answer')
      expect((saved?.core?.items?.[`${started.turn_id}:assistant`]?.metadata as any)?.mobile_turn_progress?.status)
        .toBe('completed')
    }, { timeout: 3000 })
    registration.resolve(unlisten)
    await vi.waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1))
  })

  it('emits a terminal answer without persisting intermediate stage updates', async () => {
    vi.stubEnv('VITE_MOBILE_TRACE_TURNS', '1')
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '跟踪保存超时项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'trace-model', display_name: 'Trace Model' }],
    })
    const never = deferred<void>()
    const originalSave = repository.saveLocalSnapshot.bind(repository)
    vi.spyOn(repository, 'saveLocalSnapshot').mockImplementation(async snapshot => {
      const assistant = Object.values(snapshot.core?.items || {}).find(item => item.type === 'agentMessage')
      if (snapshot.status === 'running' && (assistant?.metadata as any)?.mobile_turn_progress?.stage === 'http_send_start') {
        await never.promise
      }
      await originalSave(snapshot)
    })
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => {})
    const release = deferred<void>()
    const entered = deferred<void>()
    const runAgent = vi.fn(async () => {
      entered.resolve()
      await release.promise
      return { text: 'answer', runtimeModelId: 'trace-model', toolRounds: 0 }
    })
    let stageHandler: (payload: unknown) => void = () => {}
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, undefined, undefined,
      async handler => { stageHandler = handler; return () => {} },
    )
    const observed: CoreAppSnapshot[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(message.params as CoreAppSnapshot)
    })
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await entered.promise
    stageHandler({ turnId: started.turn_id, stage: 'http_send_start' })
    release.resolve()
    await vi.waitFor(() => {
      expect(observed.some(snapshot => snapshot.status === 'completed'
        && String(snapshot.core?.items?.[`${started.turn_id}:assistant`]?.content) === 'answer'))
        .toBe(true)
    }, { timeout: 3000 })
    await vi.waitFor(async () => {
      const saved = await repository.loadThreadSnapshot(created.session.id)
      expect(saved?.status).toBe('completed')
      expect(String(saved?.core?.items?.[`${started.turn_id}:assistant`]?.content)).toBe('answer')
    })
    expect(errorLog).not.toHaveBeenCalledWith('Standalone turn snapshot save timed out')
    errorLog.mockRestore()
  })

  it('keeps an approval waiting when model lookup fails before continuation', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '审批配置失败项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'approval-model', display_name: 'Approval Model' }],
    })
    const runAgent = vi.fn(async (input: any) => ({
      status: 'approval_required' as const,
      request: {
        requestId: `${input.turnId}:approval:0:0:call-1`,
        toolCall: { id: 'call-1', name: 'write_text_file', arguments: {} },
        message: 'Approve?',
      },
      continuation: {
        turnId: input.turnId, modelRecordId: input.modelRecordId,
        messages: [], capabilities: {}, options: {}, toolRounds: 0,
        pendingCalls: [], nextCallIndex: 0,
      },
    }))
    const resumeAgent = vi.fn()
    const transport = new StandaloneTransport(repository, config, runAgent, undefined, resumeAgent)
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'write' }],
    } })
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('waiting')
    })
    vi.spyOn(config, 'activeModel').mockRejectedValueOnce(new Error('model configuration unavailable'))
    const requestId = `${started.turn_id}:approval:0:0:call-1`
    await expect(transport.request({ method: 'approval/respond', params: {
      thread_id: created.session.id, request_id: requestId, decision: 'approve_once',
    } })).rejects.toThrow('model configuration unavailable')
    const saved = await repository.loadThreadSnapshot(created.session.id)
    expect(saved?.status).toBe('waiting')
    expect(saved?.core?.requests?.[requestId]?.status).toBe('open')
    expect(resumeAgent).not.toHaveBeenCalled()
  })

  it('keeps Stop authoritative when the initial running snapshot save is pending', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '保存 Stop 项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'stop-model', display_name: 'Stop Model' }],
    })
    const entered = deferred<void>()
    const release = deferred<void>()
    const originalSave = repository.saveLocalSnapshot.bind(repository)
    let first = true
    vi.spyOn(repository, 'saveLocalSnapshot').mockImplementation(async snapshot => {
      if (first) {
        first = false
        entered.resolve()
        await release.promise
      }
      return originalSave(snapshot)
    })
    const runAgent = vi.fn(async () => ({ text: 'late answer', runtimeModelId: 'stop-model', toolRounds: 0 }))
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, undefined, undefined, vi.fn(async () => true),
    )
    const observed: string[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(String(message.params?.status))
    })

    const start = transport.request({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'hello' }],
    } })
    await entered.promise
    const stop = transport.request({ method: 'turn/interrupt', params: { thread_id: created.session.id } })
    await vi.waitFor(() => expect((transport as any).generations.get(created.session.id)).toBe(2))
    release.resolve()
    await expect(start).rejects.toThrow('操作已取消')
    await stop
    expect(runAgent).not.toHaveBeenCalled()
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('cancelled')
    expect(observed.at(-1)).toBe('cancelled')
  })

  it('does not start approval continuation after Stop while active model lookup is pending', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '审批 Stop 项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'stop-model', display_name: 'Stop Model' }],
    })
    const runAgent = vi.fn(async (input: any) => ({
      status: 'approval_required' as const,
      request: {
        requestId: `${input.turnId}:approval:0:0:call-1`,
        toolCall: { id: 'call-1', name: 'write_text_file', arguments: {} },
        message: 'Approve?',
      },
      continuation: {
        turnId: input.turnId, modelRecordId: input.modelRecordId,
        messages: [], capabilities: {}, options: {}, toolRounds: 0,
        pendingCalls: [], nextCallIndex: 0,
      },
    }))
    const resumeAgent = vi.fn(async () => ({
      status: 'completed' as const,
      result: { text: 'late answer', runtimeModelId: 'stop-model', toolRounds: 1 },
    }))
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, resumeAgent, undefined, vi.fn(async () => true),
    )
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'write' }],
    } })
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('waiting')
    })
    const entered = deferred<void>()
    const release = deferred<void>()
    const originalActiveModel = config.activeModel.bind(config)
    vi.spyOn(config, 'activeModel').mockImplementation(async (...args) => {
      entered.resolve()
      await release.promise
      return originalActiveModel(...args)
    })
    const approval = transport.request({ method: 'approval/respond', params: {
      thread_id: created.session.id,
      request_id: `${started.turn_id}:approval:0:0:call-1`,
      decision: 'approve_once',
    } })
    await entered.promise
    await transport.request({ method: 'turn/interrupt', params: { thread_id: created.session.id } })
    release.resolve()
    await expect(approval).rejects.toThrow('审批请求已失效')
    expect(resumeAgent).not.toHaveBeenCalled()
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('cancelled')
  })

  it('keeps Stop authoritative when approval continuation is waiting on session persistence', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const created = await createStandaloneProjectClient(repository).create({ name: '续传 Stop 项目', work_root: '' })
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'stop-model', display_name: 'Stop Model' }],
    })
    const entered = deferred<void>()
    const release = deferred<void>()
    const runAgent = vi.fn(async (input: any) => ({
      status: 'approval_required' as const,
      request: {
        requestId: `${input.turnId}:approval:0:0:call-1`,
        toolCall: { id: 'call-1', name: 'write_text_file', arguments: {} },
        message: 'Approve?',
      },
      continuation: {
        turnId: input.turnId, modelRecordId: input.modelRecordId,
        messages: [], capabilities: {}, options: {}, toolRounds: 0,
        pendingCalls: [], nextCallIndex: 0,
      },
    }))
    const resumeAgent = vi.fn(async () => ({
      status: 'completed' as const,
      result: {
        text: 'late answer', runtimeModelId: 'stop-model', toolRounds: 1,
        sessionApprovedTools: ['write_text_file'],
      },
    }))
    const transport = new StandaloneTransport(
      repository, config, runAgent, undefined, resumeAgent, undefined, vi.fn(async () => true),
    )
    const observed: string[] = []
    transport.subscribe(message => {
      if (message.method === 'thread/snapshot') observed.push(String(message.params?.status))
    })
    const started = await transport.request<Record<string, unknown>>({ method: 'turn/start', params: {
      thread_id: created.session.id, input: [{ type: 'text', text: 'write' }],
    } })
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('waiting')
    })
    const originalUpdate = repository.updateLocalSession.bind(repository)
    vi.spyOn(repository, 'updateLocalSession').mockImplementation(async (...args) => {
      entered.resolve()
      await release.promise
      return originalUpdate(...args)
    })
    await transport.request({ method: 'approval/respond', params: {
      thread_id: created.session.id,
      request_id: `${started.turn_id}:approval:0:0:call-1`,
      decision: 'approve_for_session',
    } })
    await entered.promise
    await transport.request({ method: 'turn/interrupt', params: { thread_id: created.session.id } })
    release.resolve()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect((await repository.loadThreadSnapshot(created.session.id))?.status).toBe('cancelled')
    expect(observed).not.toContain('completed')
  })

  it('creates and reuses a local Study conversation binding', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const study = fakeStudy()
    const transport = new StandaloneTransport(
      repository, new StandaloneConfigStore(new MemorySecureStorage()),
      undefined, undefined, undefined, study.call,
    )

    const first = await transport.request<Record<string, unknown>>({
      method: 'study.session', params: { kind: 'map', id: 'map' },
    })
    const second = await transport.request<Record<string, unknown>>({
      method: 'study.session', params: { kind: 'map', id: 'map' },
    })

    expect(second.session_id).toBe(first.session_id)
    expect(await repository.listSessions()).toEqual([
      expect.objectContaining({
        title: '知识图谱',
        metadata: expect.objectContaining({ owner_plugin: 'study', study_scope: 'map' }),
      }),
    ])
    // The binding itself is owned by the native Study store.
    const bindings = study.calls.filter(entry => entry.method === 'study.binding.ensure')
    expect(bindings).toHaveLength(2)
    expect(bindings[0].params).toEqual(expect.objectContaining({ kind: 'map', session_id: first.session_id }))
  })

  it('reads the graph from the shared runtime instead of returning empty data', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const study = fakeStudy()
    const transport = new StandaloneTransport(
      repository, new StandaloneConfigStore(new MemorySecureStorage()),
      undefined, undefined, undefined, study.call,
    )

    await expect(transport.request({ method: 'study.get', params: { view: 'overview' } }))
      .resolves.toEqual(expect.objectContaining({
        revision: 4,
        courses: [expect.objectContaining({ name: '线性代数' })],
      }))
    await expect(transport.request({
      method: 'study.layout', params: { scope: 'overview', value: { zoom: 2 } },
    })).resolves.toBeDefined()
    expect(study.calls.map(entry => entry.method)).toEqual(['study.get', 'study.layout'])
  })

  it('sends host-owned session metadata and targets across the Study boundary', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const study = fakeStudy()
    const transport = new StandaloneTransport(
      repository, new StandaloneConfigStore(new MemorySecureStorage()),
      undefined, undefined, undefined, study.call,
    )
    const binding = await transport.request<Record<string, unknown>>({
      method: 'study.session', params: { kind: 'map', id: 'map' },
    })
    await transport.request({
      method: 'study.context',
      params: { session_id: String(binding.session_id) },
    })
    await transport.request({
      method: 'study.pin',
      params: { action: 'add', entity_type: 'session', entity_id: String(binding.session_id) },
    })

    const context = study.calls.find(entry => entry.method === 'study.context')!
    expect(context.sessionMetadata).toEqual(
      expect.objectContaining({ owner_plugin: 'study', study_scope: 'map' }),
    )
    const pin = study.calls.find(entry => entry.method === 'study.pin')!
    expect(Object.keys(pin.sessionTargets || {})).toContain(String(binding.session_id))
  })

  it('passes the active provider to Study text actions and surfaces failures', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'text-model', display_name: 'Text Model' }],
    })
    const study = fakeStudy({
      'study.text': () => {
        throw Object.assign(new Error('模型未配置'), { error: '模型未配置', reason: 'MODEL_MISSING' })
      },
    })
    const transport = new StandaloneTransport(repository, config, undefined, undefined, undefined, study.call)

    await expect(transport.request({ method: 'study.text', params: { id: 'mark-1', action: 'translate' } }))
      .rejects.toMatchObject({ message: '模型未配置', reason: 'MODEL_MISSING' })
    const text = study.calls.find(entry => entry.method === 'study.text')!
    expect(text.provider).toEqual(expect.objectContaining({
      apiKey: 'secret',
      model: expect.objectContaining({ model_id: 'text-model' }),
    }))
  })

  it('records the selected Study node on the owning map session', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const study = fakeStudy()
    const transport = new StandaloneTransport(
      repository, new StandaloneConfigStore(new MemorySecureStorage()),
      undefined, undefined, undefined, study.call,
    )
    const binding = await transport.request<Record<string, unknown>>({
      method: 'study.session', params: { kind: 'map', id: 'map' },
    })
    await transport.request({ method: 'study.current', params: { node_id: 'node-1' } })

    const sessions = await repository.listSessions()
    const mapSession = sessions.find(session => session.id === String(binding.session_id))
    expect(mapSession?.metadata).toEqual(expect.objectContaining({
      study_node_id: 'node-1',
      study_node_name: '矩阵',
    }))
  })

  it.each(['study', 'study:study'])('assembles Study prompt and tools for mode %s', async (activeMode) => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_type: 'openai', base_url: 'https://model.invalid/v1', api_key: 'secret',
      models: [{ model_id: 'study-model', display_name: 'Study Model' }],
    })
    const runAgent = vi.fn(async () => ({
      text: 'Study reply', runtimeModelId: 'study-model', toolRounds: 0,
    }))
    const study = fakeStudy()
    const transport = new StandaloneTransport(repository, config, runAgent, undefined, undefined, study.call)
    const binding = await transport.request<Record<string, unknown>>({
      method: 'study.session', params: { kind: 'map', id: 'map' },
    })
    const threadId = String(binding.session_id)

    await transport.request({ method: 'turn/start', params: {
      thread_id: threadId, input: [{ type: 'text', text: '讲解这个知识点' }], active_mode: activeMode,
    } })

    await vi.waitFor(() => expect(runAgent).toHaveBeenCalled())
    expect(runAgent).toHaveBeenCalledWith(expect.objectContaining({
      projectId: `session-${threadId}`,
      study: { enabled: true },
      disabledSkillNames: [],
      // The Study system prompt and latest context come from the shared
      // runtime rather than a hand-written string in this host.
      context: {
        modeContext: expect.stringContaining('STUDY SYSTEM PROMPT'),
      },
    }))
    expect(runAgent).toHaveBeenCalledWith(expect.objectContaining({
      context: { modeContext: expect.stringContaining('[Study latest context]') },
    }))
  })
})
