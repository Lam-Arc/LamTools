import { computed, readonly, reactive } from 'vue'

import type { CoreComposerSendMode } from '@/appServer/workbenchActions.ts'

/**
 * 消息发送行为偏好（直接引导 / 排队）。
 *
 * user:“设置中可调消息发送后直接引导或排队，默认直接引导，默认为enter，特殊发送为ctrl enter”
 * +(读侧（发送控制器）与写侧（设置面板）必须共享同一份状态，做成模块级单例；
 *   持久化沿用 localStorage 偏好键 + settings.update（core.* 命名空间）双写，
 *   与 useAssistantDisplayPreferences 等现有偏好同一套机制。)
 *
 * 语义：mode 是普通 Enter 的落点；Ctrl/Cmd+Enter 永远执行另一种（特殊发送）。
 */
export const CORE_SEND_BEHAVIOR_STORAGE_KEY = 'lamtools.core.sendBehavior'
/** 设置面板持久化用的既有设置命名空间（settings.get / settings.update）。 */
export const CORE_SEND_BEHAVIOR_NAMESPACE = 'core.sendBehavior'

export const CORE_SEND_BEHAVIOR_DEFAULT_MODE: CoreComposerSendMode = 'guide'

const state = reactive<{ mode: CoreComposerSendMode }>({ mode: CORE_SEND_BEHAVIOR_DEFAULT_MODE })

/** 只读句柄：发送控制器读取，不会误写。 */
export const coreSendBehaviorMode = readonly(state)

/** 只读 Ref 形式：发给按 Readonly<Ref<T>> 取值的控制器选项。 */
export const coreSendBehaviorModeRef = computed<CoreComposerSendMode>(() => state.mode)

export function normalizeCoreSendBehaviorMode(value: unknown): CoreComposerSendMode | null {
  return value === 'queue' || value === 'guide' ? value : null
}

function readStored(): CoreComposerSendMode | null {
  if (typeof window === 'undefined' || !window.localStorage) return null
  try {
    const raw = JSON.parse(window.localStorage.getItem(CORE_SEND_BEHAVIOR_STORAGE_KEY) || 'null')
    return normalizeCoreSendBehaviorMode(raw && typeof raw === 'object' ? (raw as Record<string, unknown>).mode : null)
  } catch {
    return null
  }
}

function writeStored(mode: CoreComposerSendMode): void {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    window.localStorage.setItem(CORE_SEND_BEHAVIOR_STORAGE_KEY, JSON.stringify({ mode }))
  } catch {
    /* 隐私模式 / 配额受限：持久化尽力而为，内存状态照常生效 */
  }
}

/** 写入偏好：更新内存状态并落到本地偏好键（设置面板额外写 settings 命名空间）。 */
export function setCoreSendBehaviorMode(mode: CoreComposerSendMode): CoreComposerSendMode {
  const next = normalizeCoreSendBehaviorMode(mode) ?? CORE_SEND_BEHAVIOR_DEFAULT_MODE
  state.mode = next
  writeStored(next)
  return next
}

/** 启动时同步一次本地偏好（模块加载即执行，首条消息就能拿到正确值）。 */
export function loadCoreSendBehaviorMode(): void {
  const stored = readStored()
  if (stored) state.mode = stored
}

loadCoreSendBehaviorMode()
