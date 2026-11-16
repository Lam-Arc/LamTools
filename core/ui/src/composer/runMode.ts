/**
 * 会话运行模式：聊天 / 工作 / Super Agent。
 *
 * user:“将现有的consider，excute迭代为 super Agent、chat、work”“新建会话时选择好，
 * 就不可变动了”+(三种模式在新建会话时选定；旧名字读进来归一到新名字，免得老会话
 * 显示出前端不认识的模式)。
 */

export const CORE_RUN_MODES = ['chat', 'work', 'auto'] as const

export type CoreRunMode = (typeof CORE_RUN_MODES)[number]

export const CORE_RUN_MODE_LABELS: Record<CoreRunMode, string> = {
  chat: '聊天',
  work: '工作',
  auto: '智能',
}

export const CORE_RUN_MODE_DESCRIPTIONS: Record<CoreRunMode, string> = {
  chat: '只讨论、查阅和分析，不改任何文件',
  work: '当场把活干完，可以改文件、跑命令',
  auto: '只对话和派工，活交给带独立工作区的子代理',
}

const LEGACY_RUN_MODES: Record<string, CoreRunMode> = {
  consider: 'chat',
  execute: 'work',
  superagent: 'auto',
}

export const DEFAULT_RUN_MODE: CoreRunMode = 'work'

/** 旧名字、空值、未知值一律落到默认模式，界面永远有东西可显示。 */
export function normalizeCoreRunMode(value: unknown): CoreRunMode {
  const raw = String(value ?? '').trim()
  const mapped = LEGACY_RUN_MODES[raw] || raw
  return (CORE_RUN_MODES as readonly string[]).includes(mapped)
    ? (mapped as CoreRunMode)
    : DEFAULT_RUN_MODE
}

export function isCoreRunModeFixed(value: unknown): boolean {
  const raw = String(value ?? '').trim()
  return raw.length > 0
}
