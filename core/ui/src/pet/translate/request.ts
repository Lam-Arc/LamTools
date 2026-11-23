/**
 * 屏幕取字之后的「翻译」：语言对、请求构造、模型挑选，全部是纯函数。
 *
 * user:“在 OCR 结果面板加「翻译」…语言对默认「自动 → 简体中文」，至少支持中/英切换；
 * 失败给可读原因（无可用模型、语言不支持、无文字）”+
 * (这一层不碰网络也不碰 DOM：谁调用、走哪条通道由 client.ts 决定，单测里零替身
 *  就能验证「请求怎么拼、哪种语言对不成立、没有模型时说什么」)。
 */
import { t } from '@/i18n/index.ts'

/** 源语言可以额外选「自动检测」；目标语言不允许。 */
export type TranslateLanguage = 'auto' | 'zh-Hans' | 'zh-Hant' | 'en' | 'ja' | 'ko'

export interface LanguageOption {
  value: TranslateLanguage
  /** 给人看的名字，也是写进提示词的名字。 */
  label: string
}

export const SOURCE_LANGUAGES: readonly LanguageOption[] = [
  { value: 'auto', label: '自动检测' },
  { value: 'zh-Hans', label: '简体中文' },
  { value: 'zh-Hant', label: '繁體中文' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
]

/** user:“语言对默认「自动 → 简体中文」”+(目标语言里不出现「自动检测」这一项)。 */
export const TARGET_LANGUAGES: readonly LanguageOption[] = SOURCE_LANGUAGES.filter(item => item.value !== 'auto')

export const DEFAULT_SOURCE: TranslateLanguage = 'auto'
export const DEFAULT_TARGET: TranslateLanguage = 'zh-Hans'

/** 原文与译文都按行对齐：后续想把译文按 lines[].bounds 叠回屏幕，靠的就是这份一一对应。 */
export interface TranslateRequest {
  system: string
  prompt: string
}

export type TranslatePair =
  | { ok: true; source: TranslateLanguage; target: TranslateLanguage }
  | { ok: false; code: 'bad-language'; reason: string }

export type TranslateBuild =
  | { ok: true; system: string; prompt: string; source: TranslateLanguage; target: TranslateLanguage }
  | { ok: false; code: 'bad-language' | 'no-text'; reason: string }

/** 直调目录里的一项（只取这里用得到的字段，多出来的不管）。 */
export interface CatalogModel {
  model_record_id?: unknown
  model_id?: unknown
  display_name?: unknown
  output_type?: unknown
  has_api_key?: unknown
}

export type ModelPick =
  | { ok: true; model: CatalogModel; keyless: boolean }
  | { ok: false; code: 'no-model'; reason: string }

function isLanguage(value: unknown): value is TranslateLanguage {
  return SOURCE_LANGUAGES.some(item => item.value === value)
}

export function languageLabel(value: unknown): string {
  const found = SOURCE_LANGUAGES.find(item => item.value === value)
  return found ? found.label : String(value ?? '')
}

/**
 * 语言对是否成立。
 *
 * user:“失败给可读原因（…语言不支持…）”+(界面上的下拉本来只会给出合法项，
 * 但通道是可以被别处调用的，所以不合法时就当场说清楚，而不是偷偷改成默认语言)。
 */
export function normalizePair(source: unknown, target: unknown): TranslatePair {
  if (!isLanguage(source) || !isLanguage(target)) {
    return {
      ok: false,
      code: 'bad-language',
      reason: t('这个语言暂时不支持翻译：{0}', { 0: `${String(source ?? '')} → ${String(target ?? '')}` }),
    }
  }
  if (target === 'auto') {
    return { ok: false, code: 'bad-language', reason: t('目标语言不能选「自动检测」。') }
  }
  if (source === target) {
    return { ok: false, code: 'bad-language', reason: t('原文和目标语言相同，不需要翻译。') }
  }
  return { ok: true, source, target }
}

/**
 * 一次翻译的提示词。
 *
 * user:“按行叠加显示（用 lines[].bounds 画回屏幕）如果成本可控就做”+
 * (所以提示词明确要求「输入几行就输出几行」，让逐行译文能在本地和原文行对上；
 *  只允许输出译文本身，界面里不会出现「以下是翻译」这类废话)。
 */
export function buildTranslateRequest(input: {
  text: string
  source: unknown
  target: unknown
}): TranslateBuild {
  const pair = normalizePair(input.source, input.target)
  if (!pair.ok) return { ok: false, code: pair.code, reason: pair.reason }
  const text = String(input.text ?? '').trim()
  if (!text) {
    return { ok: false, code: 'no-text', reason: t('这块区域里没有可翻译的文字。') }
  }
  const targetLabel = languageLabel(pair.target)
  // 提示词固定用中文写：它是给模型看的指令，不跟着界面语言变，避免译文风格随界面跳动。
  const system = `你是屏幕取字后的翻译器：把用户给的多行文本逐行翻译成${targetLabel}。只输出译文，不要解释、不要加引号、不要用 Markdown、不要重复原文；输入有几行就输出几行，行数与顺序必须保持一致。`
  const prompt = pair.source === 'auto'
    ? `请自动判断下面这段屏幕文字的语言，逐行翻译成${targetLabel}，只输出译文。\n\n${text}`
    : `下面这段屏幕文字是${languageLabel(pair.source)}，逐行翻译成${targetLabel}，只输出译文。\n\n${text}`
  return { ok: true, system, prompt, source: pair.source, target: pair.target }
}

/**
 * 从直调目录里挑一个文本模型。
 *
 * user:“失败给可读原因（无可用模型…）”+(没有文本模型时不要走到「点了没反应」：
 * 先把原因说清楚，并指向「去设置里加一个」这条动作)。
 */
export function pickTextModel(models: unknown): ModelPick {
  const list = Array.isArray(models) ? models as CatalogModel[] : []
  const textModels = list.filter(model => String(model?.output_type ?? 'text') === 'text')
  if (!textModels.length) {
    return {
      ok: false,
      code: 'no-model',
      reason: t('这台机器上还没有可用的文本模型。先在「设置 → 模型」里加一个，再回来翻译。'),
    }
  }
  // 有密钥的先上：没密钥的模型发起直调只会换来一句后端错误。
  const withKey = textModels.find(model => model.has_api_key !== false)
  return { ok: true, model: withKey ?? textModels[0], keyless: !withKey }
}
