import { beforeEach, describe, expect, it } from 'vitest'

import {
  FIRST_RUN_STORAGE_KEY,
  firstRunProgress,
  firstRunStage,
  isFirstRunClosed,
  readFirstRunMemory,
  shouldStartFirstRun,
  writeFirstRunMemory,
} from '../src/firstRun/firstRun.ts'

/**
 * user:“配置好你的 API key ，新建第一个项目与会话，发送第一条消息，就完事了”+
 * (清单必须严格从真实数据推导：少一样就停在那一样，不跳步，也不假装完成。)
 */

function memoryStorage() {
  const data = new Map<string, string>()
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, value) },
  }
}

const empty = { hasProvider: false, hasProject: false, hasSession: false, firstMessageSent: false }

describe('first run stage', () => {
  it('walks the three steps in order', () => {
    expect(firstRunStage(empty)).toBe('provider')
    expect(firstRunStage({ ...empty, hasProvider: true })).toBe('workspace')
    expect(firstRunStage({ ...empty, hasProvider: true, hasProject: true })).toBe('workspace')
    expect(firstRunStage({ ...empty, hasProvider: true, hasProject: true, hasSession: true })).toBe('message')
    expect(firstRunStage({ ...empty, hasProvider: true, hasProject: true, hasSession: true, firstMessageSent: true })).toBe('done')
  })

  it('counts a project without a session as unfinished', () => {
    const state = { hasProvider: true, hasProject: true, hasSession: false, firstMessageSent: false }
    expect(firstRunStage(state)).toBe('workspace')
    expect(firstRunProgress(state)).toEqual({ done: 1, total: 3 })
  })

  it('reports progress that matches the stage', () => {
    expect(firstRunProgress(empty)).toEqual({ done: 0, total: 3 })
    expect(firstRunProgress({ hasProvider: true, hasProject: true, hasSession: true, firstMessageSent: true }))
      .toEqual({ done: 3, total: 3 })
  })
})

describe('first run memory', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns defaults for missing or broken records', () => {
    const storage = memoryStorage()
    expect(readFirstRunMemory(storage)).toMatchObject({ completed: false, dismissed: false })
    storage.setItem(FIRST_RUN_STORAGE_KEY, 'nope')
    expect(readFirstRunMemory(storage)).toMatchObject({ completed: false, dismissed: false })
    storage.setItem(FIRST_RUN_STORAGE_KEY, JSON.stringify({ dismissed: 'yes', completed: 1 }))
    expect(readFirstRunMemory(storage)).toMatchObject({ completed: false, dismissed: false })
  })

  it('merges patches instead of dropping earlier flags', () => {
    const storage = memoryStorage()
    writeFirstRunMemory({ dismissed: true }, storage)
    const next = writeFirstRunMemory({ completed: true }, storage)
    expect(next.dismissed).toBe(true)
    expect(next.completed).toBe(true)
    expect(readFirstRunMemory(storage).completed).toBe(true)
  })

  it('treats either exit as closed', () => {
    expect(isFirstRunClosed({ version: 1, completed: false, dismissed: false, updatedAt: 0 })).toBe(false)
    expect(isFirstRunClosed({ version: 1, completed: true, dismissed: false, updatedAt: 0 })).toBe(true)
    expect(isFirstRunClosed({ version: 1, completed: false, dismissed: true, updatedAt: 0 })).toBe(true)
  })

  it('never nags users who already have sessions', () => {
    localStorage.clear()
    expect(shouldStartFirstRun(false)).toBe(true)
    expect(shouldStartFirstRun(true)).toBe(false)

    writeFirstRunMemory({ completed: true })
    expect(shouldStartFirstRun(false)).toBe(false)

    localStorage.clear()
    writeFirstRunMemory({ dismissed: true })
    expect(shouldStartFirstRun(false)).toBe(false)
  })
})
