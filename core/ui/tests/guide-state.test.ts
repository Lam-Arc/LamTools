import { beforeEach, describe, expect, it } from 'vitest'

import {
  GUIDE_STORAGE_KEY,
  clampGuideIndex,
  readGuideMemory,
  resolveResumeIndex,
  useGuide,
  writeGuideMemory,
} from '../src/guide/useGuide.ts'

/** 内存存储：不依赖浏览器，也能断言到底写进去了什么。 */
function memoryStorage() {
  const data = new Map<string, string>()
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, value) },
    raw: data,
  }
}

describe('guide memory', () => {
  it('falls back to defaults for missing or broken records', () => {
    const empty = memoryStorage()
    expect(readGuideMemory(empty)).toMatchObject({ completed: false, mode: 'full', beginner: true, stepId: '' })
    empty.setItem(GUIDE_STORAGE_KEY, '{not json')
    expect(readGuideMemory(empty).completed).toBe(false)
    empty.setItem(GUIDE_STORAGE_KEY, JSON.stringify({ mode: 'weird', seen: [1, 'a'] }))
    const parsed = readGuideMemory(empty)
    expect(parsed.mode).toBe('full')
    expect(parsed.seen).toEqual(['a'])
  })

  it('merges patches without dropping earlier fields', () => {
    const storage = memoryStorage()
    writeGuideMemory({ mode: 'quick', stepId: 'x' }, storage)
    const next = writeGuideMemory({ completed: true }, storage)
    expect(next.mode).toBe('quick')
    expect(next.stepId).toBe('x')
    expect(next.completed).toBe(true)
    expect(readGuideMemory(storage).completed).toBe(true)
  })

  it('resumes from the stored step and falls back when it disappeared', () => {
    const steps = [{ step: { id: 'a' } }, { step: { id: 'b' } }]
    expect(resolveResumeIndex(steps, 'b')).toBe(1)
    expect(resolveResumeIndex(steps, 'gone')).toBe(0)
    expect(resolveResumeIndex(steps, '')).toBe(0)
  })

  it('clamps indexes instead of trusting arithmetic', () => {
    expect(clampGuideIndex(-5, 10)).toBe(0)
    expect(clampGuideIndex(99, 10)).toBe(9)
    expect(clampGuideIndex(3.4, 10)).toBe(3)
    expect(clampGuideIndex(2, 0)).toBe(0)
  })
})

describe('guide session', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('builds a shorter path for the quick tour', () => {
    const guide = useGuide()
    guide.begin({ mode: 'quick', beginner: false, hasProvider: true })
    expect(guide.total.value).toBe(9)
    expect(guide.current.value?.chapterId).toBe('welcome')
    expect(guide.options.value.beginner).toBe(false)
  })

  it('walks forward, backward and persists the current step', () => {
    const guide = useGuide()
    guide.begin({ mode: 'quick', beginner: false, hasProvider: true })
    const first = guide.current.value?.step.id
    guide.next()
    expect(guide.index.value).toBe(1)
    expect(readGuideMemory().stepId).toBe(guide.current.value?.step.id)
    guide.back()
    expect(guide.current.value?.step.id).toBe(first)
    expect(readGuideMemory().stepId).toBe(first)
    expect(guide.seen.value).toContain(first!)
  })

  it('skips the whole chapter and lands on the next one', () => {
    const guide = useGuide()
    guide.begin({ mode: 'quick', beginner: false, hasProvider: true })
    expect(guide.current.value?.chapterId).toBe('welcome')
    guide.skipChapter()
    expect(guide.current.value?.chapterId).toBe('interface')
    expect(guide.index.value).toBe(3)
  })

  it('finishes only once and clears the resume point', () => {
    const guide = useGuide()
    guide.begin({ mode: 'quick', beginner: false, hasProvider: true })
    guide.finish()
    expect(guide.active.value).toBe(false)
    const memory = readGuideMemory()
    expect(memory.completed).toBe(true)
    expect(memory.stepId).toBe('')
  })

  it('keeps the resume point when the user stops mid-way', () => {
    const guide = useGuide()
    guide.begin({ mode: 'full', beginner: true, hasProvider: false })
    guide.next()
    const stepId = guide.current.value?.step.id
    guide.stop()
    const memory = readGuideMemory()
    expect(memory.completed).toBe(false)
    expect(memory.stepId).toBe(stepId)
  })

  it('resumes from the last step instead of starting over', () => {
    const guide = useGuide()
    guide.begin({ mode: 'quick', beginner: false, hasProvider: true })
    guide.next()
    guide.next()
    guide.stop()
    const stepId = guide.current.value?.step.id

    const resumed = useGuide()
    resumed.resume(true)
    expect(resumed.current.value?.step.id).toBe(stepId)
  })
})
