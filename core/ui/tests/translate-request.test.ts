import { describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_SOURCE,
  DEFAULT_TARGET,
  buildTranslateRequest,
  languageLabel,
  normalizePair,
  pickTextModel,
  type CatalogModel,
} from '../src/pet/translate/request.ts'
import { TranslateFailure, createTranslator } from '../src/pet/translate/client.ts'

// user:“在 OCR 结果面板加「翻译」…语言对默认「自动 → 简体中文」，至少支持中/英切换；
// 失败给可读原因（无可用模型、语言不支持、无文字）”+
// (先证明「请求怎么拼、语言对怎么映射、失败怎么说人话」，再接到界面上。)
const textModel: CatalogModel = {
  model_record_id: 'm-text',
  display_name: '通用文本',
  model_id: 'gpt-x',
  output_type: 'text',
  has_api_key: true,
}
const imageModel: CatalogModel = {
  model_record_id: 'm-image',
  display_name: '出图',
  model_id: 'img-x',
  output_type: 'image',
  has_api_key: true,
}
const keylessModel: CatalogModel = { ...textModel, model_record_id: 'm-nokey', display_name: '没密钥', has_api_key: false }

describe('语言对', () => {
  it('默认是「自动 → 简体中文」', () => {
    expect(DEFAULT_SOURCE).toBe('auto')
    expect(DEFAULT_TARGET).toBe('zh-Hans')
  })

  it('中英互译都成立，源语言可以用自动', () => {
    expect(normalizePair('auto', 'zh-Hans')).toEqual({ ok: true, source: 'auto', target: 'zh-Hans' })
    expect(normalizePair('zh-Hans', 'en')).toEqual({ ok: true, source: 'zh-Hans', target: 'en' })
    expect(normalizePair('en', 'zh-Hans')).toEqual({ ok: true, source: 'en', target: 'zh-Hans' })
  })

  it('不认识的语言给可读原因，而不是静默改成默认值', () => {
    const result = normalizePair('kl', 'zh-Hans')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.reason).toContain('不支持')
  })

  it('不能翻译成「自动检测」，也不能原文与目标相同', () => {
    const auto = normalizePair('auto', 'auto')
    expect(auto.ok).toBe(false)
    if (!auto.ok) expect(auto.reason).toContain('目标语言')

    const same = normalizePair('en', 'en')
    expect(same.ok).toBe(false)
    if (!same.ok) expect(same.reason).toContain('相同')
  })

  it('语言名是给人看的字面量', () => {
    expect(languageLabel('zh-Hans')).toBe('简体中文')
    expect(languageLabel('en')).toBe('English')
    expect(languageLabel('auto')).toBe('自动检测')
  })
})

describe('翻译请求构造', () => {
  it('把原文、目标语言和「只输出译文」写进请求', () => {
    const built = buildTranslateRequest({ text: 'Hello world\nSecond line', source: 'auto', target: 'zh-Hans' })
    expect(built.ok).toBe(true)
    if (!built.ok) return
    expect(built.system).toContain('只输出译文')
    expect(built.system).toContain('简体中文')
    // 行数必须保持：后续按行叠回屏幕依赖这份一一对应。
    expect(built.system).toContain('行数')
    expect(built.prompt).toContain('Hello world\nSecond line')
    // 源语言是「自动」时由模型自己判断，不硬塞一个语言名。
    expect(built.prompt).toContain('自动判断')
  })

  it('指定源语言时写清原文语言，不再让模型猜', () => {
    const built = buildTranslateRequest({ text: 'Hello', source: 'en', target: 'zh-Hans' })
    expect(built.ok).toBe(true)
    if (!built.ok) return
    expect(built.prompt).toContain('English')
    expect(built.prompt).not.toContain('自动判断')
  })

  it('没有文字就不发请求，理由说清楚', () => {
    const empty = buildTranslateRequest({ text: '   \n ', source: 'auto', target: 'zh-Hans' })
    expect(empty.ok).toBe(false)
    if (!empty.ok) expect(empty.reason).toContain('文字')
  })

  it('语言对不合法时直接给出原因，不构造请求', () => {
    const built = buildTranslateRequest({ text: 'Hello', source: 'en', target: 'en' })
    expect(built.ok).toBe(false)
    if (!built.ok) expect(built.reason).toContain('相同')
  })
})

describe('模型挑选', () => {
  it('只在文本模型里挑，跳过出图模型', () => {
    const picked = pickTextModel([imageModel, textModel])
    expect(picked.ok).toBe(true)
    if (picked.ok) expect(picked.model.model_record_id).toBe('m-text')
  })

  it('优先挑配了密钥的文本模型', () => {
    const picked = pickTextModel([keylessModel, textModel])
    expect(picked.ok).toBe(true)
    if (picked.ok) expect(picked.model.model_record_id).toBe('m-text')
  })

  it('一个文本模型都没有时给出可操作的原因', () => {
    const picked = pickTextModel([imageModel])
    expect(picked.ok).toBe(false)
    if (!picked.ok) expect(picked.reason).toContain('文本模型')
  })

  it('目录为空也走同一条原因', () => {
    const picked = pickTextModel(undefined)
    expect(picked.ok).toBe(false)
  })
})

/** 一个按方法名分发的假 RPC：把 direct.* 的时序写清楚，不连后端。 */
function fakeRpc(handlers: Record<string, (params: Record<string, unknown>) => unknown>) {
  const calls: { method: string; params: Record<string, unknown> }[] = []
  const rpc = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    calls.push({ method, params })
    const handler = handlers[method]
    if (!handler) throw new Error(`unexpected method ${method}`)
    return handler(params) as Record<string, unknown>
  })
  return { rpc, calls }
}

describe('翻译通道（直调 direct.*）', () => {
  it('成功路径：挑模型 → 发起直调 → 轮询到完成', async () => {
    const { rpc, calls } = fakeRpc({
      'direct.catalog': () => ({ models: [imageModel, textModel] }),
      'direct.run': () => ({ call: { id: 'c1', status: 'queued' } }),
      'direct.get': () => ({
        call: { id: 'c1', status: 'completed', results: [{ index: 0, status: 'ok', text: '你好\n第二行' }] },
      }),
    })
    const translate = createTranslator(rpc, { pollMs: 0 })
    const outcome = await translate({ text: 'Hello\nSecond line', source: 'auto', target: 'zh-Hans' })
    expect(outcome.text).toBe('你好\n第二行')
    expect(outcome.model).toBe('通用文本')
    expect(calls.map(call => call.method)).toEqual(['direct.catalog', 'direct.run', 'direct.get'])
    expect(calls[1].params.model_ref).toBe('m-text')
    expect(String((calls[1].params.prompts as string[])[0])).toContain('Hello\nSecond line')
  })

  it('没有可用文本模型：不发直调，理由可读', async () => {
    const { rpc, calls } = fakeRpc({ 'direct.catalog': () => ({ models: [imageModel] }) })
    const translate = createTranslator(rpc, { pollMs: 0 })
    await expect(translate({ text: 'Hello', source: 'auto', target: 'zh-Hans' }))
      .rejects.toMatchObject({ code: 'no-model' })
    expect(calls.map(call => call.method)).toEqual(['direct.catalog'])
  })

  it('语言不支持：连模型目录都不读', async () => {
    const { rpc, calls } = fakeRpc({})
    const translate = createTranslator(rpc, { pollMs: 0 })
    await expect(translate({ text: 'Hello', source: 'auto', target: 'auto' as never }))
      .rejects.toMatchObject({ code: 'bad-language' })
    expect(calls).toHaveLength(0)
  })

  it('没有文字：不发起任何请求', async () => {
    const { rpc, calls } = fakeRpc({})
    const translate = createTranslator(rpc, { pollMs: 0 })
    await expect(translate({ text: '   ', source: 'auto', target: 'zh-Hans' }))
      .rejects.toMatchObject({ code: 'no-text' })
    expect(calls).toHaveLength(0)
  })

  it('模型侧失败：把后端的错误原样变成可读原因', async () => {
    const { rpc } = fakeRpc({
      'direct.catalog': () => ({ models: [textModel] }),
      'direct.run': () => ({ call: { id: 'c2', status: 'queued' } }),
      'direct.get': () => ({
        call: { id: 'c2', status: 'failed', error: '模型配置不可用：缺少 API Key' },
      }),
    })
    const translate = createTranslator(rpc, { pollMs: 0 })
    const failure = await translate({ text: 'Hello', source: 'auto', target: 'zh-Hans' }).catch(error => error)
    expect(failure).toBeInstanceOf(TranslateFailure)
    expect(failure.code).toBe('model-error')
    expect(failure.message).toContain('缺少 API Key')
  })

  it('直调发起就被拒（没有模型等）：保留后端那句话', async () => {
    const { rpc } = fakeRpc({
      'direct.catalog': () => ({ models: [textModel] }),
      'direct.run': () => { throw new Error('模型已停用') },
    })
    const translate = createTranslator(rpc, { pollMs: 0 })
    await expect(translate({ text: 'Hello', source: 'auto', target: 'zh-Hans' }))
      .rejects.toMatchObject({ code: 'request-failed' })
  })

  it('模型返回空译文：说清是「没返回译文」而不是空白框', async () => {
    const { rpc } = fakeRpc({
      'direct.catalog': () => ({ models: [textModel] }),
      'direct.run': () => ({ call: { id: 'c3', status: 'queued' } }),
      'direct.get': () => ({ call: { id: 'c3', status: 'completed', results: [{ index: 0, status: 'ok', text: '  ' }] } }),
    })
    const translate = createTranslator(rpc, { pollMs: 0 })
    await expect(translate({ text: 'Hello', source: 'auto', target: 'zh-Hans' }))
      .rejects.toMatchObject({ code: 'empty-result' })
  })

  it('一直排队到超时：给超时原因，不无限等', async () => {
    const { rpc } = fakeRpc({
      'direct.catalog': () => ({ models: [textModel] }),
      'direct.run': () => ({ call: { id: 'c4', status: 'queued' } }),
      'direct.get': () => ({ call: { id: 'c4', status: 'running', results: [{ index: 0, status: 'pending', text: '' }] } }),
    })
    let clock = 0
    const translate = createTranslator(rpc, {
      pollMs: 0,
      deadlineMs: 1000,
      now: () => (clock += 600),
      sleep: async () => undefined,
    })
    const failure = await translate({ text: 'Hello', source: 'auto', target: 'zh-Hans' }).catch(error => error)
    expect(failure.code).toBe('timeout')
    expect(failure.message).toContain('秒')
  })
})
