/**
 * 屏幕翻译走的通道：**复用直调（direct.*）**，不新开第三方翻译接口。
 *
 * user:“用现有模型直调通道（core/src/lamtools_core/direct/executor.py）…不要接第三方翻译 API”+
 * (选项理由：屏幕翻译是一次性文本变换——不需要工具、不需要会话上下文，也不该在聊天记录里
 *  留下一条消息。直调通道的设计目标正是「不进 Agent Loop 的一条直路」；截图窗口本来就握着
 *  同一套 DirectTransport，后端已有 direct.catalog / direct.run / direct.get，因此这条路
 *  不新增任何后端代码。Agent 通道虽然一句话就能发，但会把一次取字翻译写进目标会话的
 *  聊天历史，还要付出 agent loop 的工具编排开销与不可控延迟。)
 */
import {
  buildTranslateRequest,
  pickTextModel,
  type TranslateLanguage,
} from './request.ts'
import { t } from '@/i18n/index.ts'

/** 直调失败的可读分类：界面按 code 决定说哪句话，消息里已经是可以直接显示的中文。 */
export type TranslateFailureCode =
  | 'bad-language'
  | 'no-text'
  | 'no-model'
  | 'request-failed'
  | 'model-error'
  | 'empty-result'
  | 'timeout'

export class TranslateFailure extends Error {
  code: TranslateFailureCode

  constructor(code: TranslateFailureCode, message: string) {
    super(message)
    this.name = 'TranslateFailure'
    this.code = code
  }
}

export interface TranslateInput {
  text: string
  source: TranslateLanguage | string
  target: TranslateLanguage | string
}

export interface TranslateOutcome {
  /** 译文（按原文的换行对齐）。 */
  text: string
  /** 这次用的是哪个模型：界面上标一句，出问题好对照。 */
  model: string
}

/** 走 JSON-RPC 的最小形状；截图窗口与主界面各自注入自己的 transport。 */
export type TranslateRpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>

export interface TranslatorOptions {
  /** 轮询间隔：直调是「先建任务再出结果」，所以要问几次。 */
  pollMs?: number
  /** 等译文的总时长上限，到点给超时原因，不无限等。 */
  deadlineMs?: number
  now?: () => number
  sleep?: (ms: number) => Promise<void>
  /** 让直调落在指定项目下（影响模型/供应商配置的解析范围）。 */
  projectId?: string
}

export type Translator = (input: TranslateInput) => Promise<TranslateOutcome>

const DEFAULT_POLL_MS = 400
const DEFAULT_DEADLINE_MS = 90_000

function recordOf(payload: unknown): Record<string, unknown> {
  const call = (payload as { call?: unknown } | null)?.call
  return call && typeof call === 'object' ? call as Record<string, unknown> : {}
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/**
 * 造一个翻译器：挑模型 → 发起直调 → 问到出结果。
 *
 * user:“失败给可读原因（无可用模型、语言不支持、无文字）”+(每一处失败都抛
 * TranslateFailure，界面只负责把 message 显示出来，不再自己补词)。
 */
export function createTranslator(rpc: TranslateRpc, options: TranslatorOptions = {}): Translator {
  const pollMs = options.pollMs ?? DEFAULT_POLL_MS
  const deadlineMs = options.deadlineMs ?? DEFAULT_DEADLINE_MS
  const now = options.now ?? (() => Date.now())
  const sleep = options.sleep ?? ((ms: number) => new Promise<void>(resolve => {
    window.setTimeout(resolve, ms)
  }))

  return async (input: TranslateInput): Promise<TranslateOutcome> => {
    const built = buildTranslateRequest(input)
    if (!built.ok) throw new TranslateFailure(built.code, built.reason)
    const scope = options.projectId ? { project_id: options.projectId } : {}

    let catalog: Record<string, unknown>
    try {
      catalog = await rpc('direct.catalog', scope)
    } catch (error) {
      throw new TranslateFailure('request-failed', t('读不到模型目录：{0}', { 0: messageOf(error) }))
    }
    const picked = pickTextModel(catalog?.models)
    if (!picked.ok) throw new TranslateFailure(picked.code, picked.reason)
    const modelRef = String(picked.model.model_record_id ?? '')
    const modelName = String(picked.model.display_name ?? picked.model.model_id ?? modelRef)

    let callId = ''
    try {
      const started = await rpc('direct.run', {
        model_ref: modelRef,
        prompts: [built.prompt],
        system: built.system,
        params: {},
        ...scope,
      })
      callId = String(recordOf(started).id ?? '')
      if (!callId) throw new Error(t('后端没有返回这次调用的编号'))
    } catch (error) {
      throw new TranslateFailure('request-failed', messageOf(error))
    }

    const deadline = now() + deadlineMs
    while (now() < deadline) {
      const record = recordOf(await rpc('direct.get', { call_id: callId }))
      const status = String(record.status ?? '')
      if (status === 'completed') {
        const results = Array.isArray(record.results) ? record.results as Record<string, unknown>[] : []
        const first = results[0] ?? {}
        const failure = String(first.error ?? '')
        if (failure) throw new TranslateFailure('model-error', failure)
        const text = String(first.text ?? '').trim()
        if (!text) throw new TranslateFailure('empty-result', t('模型没有返回译文，可以换一个模型再试。'))
        return { text, model: modelName }
      }
      if (status === 'failed' || status === 'cancelled') {
        const detail = String(record.error ?? '').trim()
        throw new TranslateFailure('model-error', detail || t('这次翻译失败了，可以换一个模型再试。'))
      }
      await sleep(pollMs)
    }
    throw new TranslateFailure('timeout', t('翻译等待超时（{0} 秒）：模型一直没返回结果。', {
      0: String(Math.round(deadlineMs / 1000)),
    }))
  }
}
