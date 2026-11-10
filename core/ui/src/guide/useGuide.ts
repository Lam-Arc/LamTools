import { computed, ref } from 'vue'

import { buildGuideChapters, flattenGuideSteps } from '@/guide/guideScript.ts'
import type { GuideMode, GuideOptions } from '@/guide/types.ts'

/**
 * 引导的进度与推进逻辑。
 *
 * user:“诉求是让哪怕没接触过电脑的小白也能用明白sunday”+
 * (进度必须能恢复：小白天生容易被打断（接电话、点错、关掉应用）。下次打开
 *  时从上次那一句继续，而不是从头再讲一遍；走完之后不再自动弹，但入口常驻。)
 */

export const GUIDE_STORAGE_KEY = 'lamtools.core.guide.v1'

export interface GuideMemory {
  version: 1
  /** 完整走过一次（或主动放弃）后置真：之后不再自动弹出。 */
  completed: boolean
  /** 是否加入电脑基本功章节。 */
  beginner: boolean
  /** 上次选择的详细程度。 */
  mode: GuideMode
  /** 走到哪一句，用于下次续上。 */
  stepId: string
  /** 已完成到过的步骤，用于目录里的勾。 */
  seen: string[]
  updatedAt: number
}

const DEFAULT_MEMORY: GuideMemory = {
  version: 1,
  completed: false,
  beginner: true,
  mode: 'full',
  stepId: '',
  seen: [],
  updatedAt: 0,
}

type GuideStorage = Pick<Storage, 'getItem' | 'setItem'>

function storageOrNull(): GuideStorage | null {
  if (typeof localStorage === 'undefined') return null
  try {
    // 隐私模式会抛：探测一次，之后直接当作没有存储。
    localStorage.getItem(GUIDE_STORAGE_KEY)
    return localStorage
  } catch {
    return null
  }
}

export function readGuideMemory(storage: GuideStorage | null = storageOrNull()): GuideMemory {
  if (!storage) return { ...DEFAULT_MEMORY, seen: [] }
  try {
    const raw = storage.getItem(GUIDE_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_MEMORY, seen: [] }
    const value = JSON.parse(raw) as Partial<GuideMemory> | null
    if (!value || typeof value !== 'object') return { ...DEFAULT_MEMORY, seen: [] }
    return {
      version: 1,
      completed: value.completed === true,
      beginner: value.beginner !== false,
      mode: value.mode === 'quick' ? 'quick' : 'full',
      stepId: typeof value.stepId === 'string' ? value.stepId : '',
      seen: Array.isArray(value.seen) ? value.seen.filter((id): id is string => typeof id === 'string') : [],
      updatedAt: Number(value.updatedAt) || 0,
    }
  } catch {
    return { ...DEFAULT_MEMORY, seen: [] }
  }
}

export function writeGuideMemory(
  patch: Partial<Omit<GuideMemory, 'version'>>,
  storage: GuideStorage | null = storageOrNull(),
): GuideMemory {
  const next: GuideMemory = {
    ...readGuideMemory(storage),
    ...patch,
    version: 1,
    updatedAt: Date.now(),
  }
  if (storage) {
    try {
      storage.setItem(GUIDE_STORAGE_KEY, JSON.stringify(next))
    } catch {
      // 存不下不影响这一次的使用。
    }
  }
  return next
}

/** 从上次那一句续上；找不到（文案改过、步骤删了）就从第一句开始。 */
export function resolveResumeIndex(steps: Array<{ step: { id: string } }>, stepId: string): number {
  if (!stepId) return 0
  const index = steps.findIndex(item => item.step.id === stepId)
  return index >= 0 ? index : 0
}

export function clampGuideIndex(index: number, total: number): number {
  if (total <= 0) return 0
  return Math.min(Math.max(0, Math.round(index)), total - 1)
}

export interface GuideSessionOptions extends GuideOptions {
  /** 从这一句开始；缺省则从头。 */
  resumeStepId?: string
}

/**
 * 一次引导会话。组件只读 `current` 和 `progress`，推进走四个动作：
 * next / back / skipChapter / finish。所有动作都同步写回 localStorage。
 */
export function useGuide() {
  const active = ref(false)
  const options = ref<GuideOptions>({ mode: 'full', beginner: true, hasProvider: false })
  const index = ref(0)
  const seen = ref<string[]>([])

  const chapters = computed(() => buildGuideChapters(options.value))
  const steps = computed(() => flattenGuideSteps(chapters.value))
  const total = computed(() => steps.value.length)
  const current = computed(() => steps.value[clampGuideIndex(index.value, total.value)] ?? null)
  const progress = computed(() => (total.value > 0 ? (index.value + 1) / total.value : 0))
  const isLast = computed(() => index.value >= total.value - 1)
  const isFirst = computed(() => index.value <= 0)

  function persist(stepId?: string): void {
    const id = stepId ?? current.value?.step.id ?? ''
    const nextSeen = id && !seen.value.includes(id) ? [...seen.value, id] : seen.value
    seen.value = nextSeen
    writeGuideMemory({
      mode: options.value.mode,
      beginner: options.value.beginner,
      stepId: id,
      seen: nextSeen,
    })
  }

  function begin(session: GuideSessionOptions): void {
    options.value = {
      mode: session.mode,
      beginner: session.beginner,
      hasProvider: session.hasProvider,
    }
    active.value = true
    index.value = resolveResumeIndex(steps.value, session.resumeStepId || '')
    persist()
  }

  /** 从上次的位置继续；没有记录就从头。 */
  function resume(hasProvider: boolean): void {
    const memory = readGuideMemory()
    begin({
      mode: memory.mode,
      beginner: memory.beginner,
      hasProvider,
      resumeStepId: memory.stepId,
    })
  }

  function next(): void {
    if (isLast.value) {
      finish()
      return
    }
    index.value = clampGuideIndex(index.value + 1, total.value)
    persist()
  }

  function back(): void {
    index.value = clampGuideIndex(index.value - 1, total.value)
    persist()
  }

  /** 跳过整章：同一章的步骤全部跳掉，落在下一章第一句。 */
  function skipChapter(): void {
    const now = current.value
    if (!now) return
    const target = steps.value.findIndex(item => item.chapterIndex > now.chapterIndex)
    if (target < 0) {
      finish()
      return
    }
    index.value = target
    persist()
  }

  function finish(): void {
    active.value = false
    writeGuideMemory({ completed: true, stepId: '', seen: seen.value })
  }

  /** 中途退出（不是走完）：记录位置和 completed=false，下次接着来。 */
  function stop(): void {
    active.value = false
    persist()
  }

  function restart(session: Omit<GuideSessionOptions, 'resumeStepId'>): void {
    begin({ ...session, resumeStepId: '' })
  }

  return {
    active,
    options,
    chapters,
    steps,
    total,
    current,
    index,
    progress,
    isFirst,
    isLast,
    seen,
    begin,
    resume,
    next,
    back,
    skipChapter,
    finish,
    stop,
    restart,
  }
}

/** 首次进入时判断要不要自动拉起引导。 */
export function shouldAutoStartGuide(alreadyShownOnboarding: boolean): boolean {
  const memory = readGuideMemory()
  if (memory.completed) return false
  // 让现有「配置模型」向导先说完，避免两个浮层叠在一起。
  return !alreadyShownOnboarding
}
