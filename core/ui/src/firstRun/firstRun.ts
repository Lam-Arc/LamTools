/**
 * 开工清单的状态与记忆。
 *
 * user:“配置好你的 API key ，新建第一个项目与会话，发送第一条消息，就完事了”+
 * (First-run 只做这三件事：配模型、建项目与会话、发第一句话。做完就收，
 *  不讲功能、不讲快捷键、不教用电脑。)
 *
 * 状态一律从应用的真实数据推导：有 key、有项目、有会话、当前会话里发过
 * 用户消息。这样清单不会“假装完成”，也不会要求用户重复已经做过的事。
 */

export const FIRST_RUN_STORAGE_KEY = 'lamtools.core.first-run.v1'

export type FirstRunStage = 'provider' | 'workspace' | 'message' | 'done'

export interface FirstRunState {
  hasProvider: boolean
  hasProject: boolean
  hasSession: boolean
  firstMessageSent: boolean
}

export interface FirstRunProgress {
  done: number
  total: number
}

/** 三步：模型 → 项目与会话 → 第一句话。 */
export const FIRST_RUN_TOTAL = 3

export function firstRunStage(state: FirstRunState): FirstRunStage {
  if (!state.hasProvider) return 'provider'
  // 项目建好时会自动带一个会话；只有项目没有会话时也算没走完这一步。
  if (!state.hasProject || !state.hasSession) return 'workspace'
  if (!state.firstMessageSent) return 'message'
  return 'done'
}

export function firstRunProgress(state: FirstRunState): FirstRunProgress {
  let done = 0
  if (state.hasProvider) done += 1
  if (state.hasProject && state.hasSession) done += 1
  if (state.firstMessageSent) done += 1
  return { done, total: FIRST_RUN_TOTAL }
}

export interface FirstRunMemory {
  version: 1
  /** 三步都走完。 */
  completed: boolean
  /** 用户手动收起：不再打扰，但也不算走完。 */
  dismissed: boolean
  updatedAt: number
}

const DEFAULT_MEMORY: FirstRunMemory = {
  version: 1,
  completed: false,
  dismissed: false,
  updatedAt: 0,
}

type FirstRunStorage = Pick<Storage, 'getItem' | 'setItem'>

function storageOrNull(): FirstRunStorage | null {
  if (typeof localStorage === 'undefined') return null
  try {
    localStorage.getItem(FIRST_RUN_STORAGE_KEY)
    return localStorage
  } catch {
    return null
  }
}

export function readFirstRunMemory(storage: FirstRunStorage | null = storageOrNull()): FirstRunMemory {
  if (!storage) return { ...DEFAULT_MEMORY }
  try {
    const raw = storage.getItem(FIRST_RUN_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_MEMORY }
    const value = JSON.parse(raw) as Partial<FirstRunMemory> | null
    if (!value || typeof value !== 'object') return { ...DEFAULT_MEMORY }
    return {
      version: 1,
      completed: value.completed === true,
      dismissed: value.dismissed === true,
      updatedAt: Number(value.updatedAt) || 0,
    }
  } catch {
    return { ...DEFAULT_MEMORY }
  }
}

export function writeFirstRunMemory(
  patch: Partial<Omit<FirstRunMemory, 'version'>>,
  storage: FirstRunStorage | null = storageOrNull(),
): FirstRunMemory {
  const next: FirstRunMemory = {
    ...readFirstRunMemory(storage),
    ...patch,
    version: 1,
    updatedAt: Date.now(),
  }
  if (storage) {
    try {
      storage.setItem(FIRST_RUN_STORAGE_KEY, JSON.stringify(next))
    } catch {
      // 存不下不影响这一次的使用。
    }
  }
  return next
}

/** 走完或主动收起后都不再自动出现。 */
export function isFirstRunClosed(memory: FirstRunMemory): boolean {
  return memory.completed || memory.dismissed
}

/**
 * 老用户不打扰：本次启动前就已经有会话，说明他们早就过了这一关。
 * 新装用户第一次进来时还没有会话，清单才会出现。
 */
export function shouldStartFirstRun(hasExistingSessions: boolean): boolean {
  if (hasExistingSessions) return false
  return !isFirstRunClosed(readFirstRunMemory())
}
