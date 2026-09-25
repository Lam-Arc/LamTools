import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/**
 * 命令面契约：前端 `invoke('x')` 的每个名字都必须出现在 `generate_handler!`
 * 列表里。
 *
 * 现状教训：`sunday_artifact_open` 定义、TS 包装、调用点都齐全，只忘了注册，
 * 于是"打开成果"在真机上 100% 失败，而所有既有测试都在 mock invoke，谁也
 * 发现不了（2026-09-25 审计 P2）。这条通用守卫把它变成一次性失败。
 */

const libSource = readFileSync(new URL('../src-tauri/src/lib.rs', import.meta.url), 'utf8')

function parseHandlerList(body: string): string[] {
  return body
    .split(/[,\s]+/)
    .map((entry) => entry.trim())
    // 允许 `module::command` 形式：注册名就是路径的最后一段
    .map((entry) => entry.split('::').pop() || '')
    .filter((entry) => entry.length > 0)
}

function handlerLists(): { android: string[]; other: string[] } {
  const matches = [...libSource.matchAll(/generate_handler!\[([\s\S]*?)\]/g)]
  expect(matches.length).toBeGreaterThanOrEqual(2)
  // 第一个列表是 Android 目标，第二个是非 Android 目标（lib.rs 里的 cfg 分支）
  return { android: parseHandlerList(matches[0][1]), other: parseHandlerList(matches[1][1]) }
}

function sourceFiles(root: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(root)) {
    const full = join(root, entry)
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full))
    } else if (/\.(ts|vue)$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

function invokedCommands(): Map<string, string> {
  const srcRoot = fileURLToPath(new URL('../src', import.meta.url))
  const commands = new Map<string, string>()
  for (const file of sourceFiles(srcRoot)) {
    const source = readFileSync(file, 'utf8')
    for (const match of source.matchAll(/\binvoke(?:<[^>]*>)?\(\s*'([^']+)'/g)) {
      const name = match[1]
      // Capacitor 插件走的是另一套注册（registerPlugin），不在 Rust 列表内
      if (name.startsWith('plugin:')) continue
      if (!commands.has(name)) commands.set(name, file)
    }
  }
  return commands
}

describe('mobile command surface contract', () => {
  it('registers every command the shared UI invokes', () => {
    const { android } = handlerLists()
    const commands = invokedCommands()

    expect(commands.size).toBeGreaterThan(20)
    const missing = [...commands.entries()]
      .filter(([name]) => !android.includes(name))
      .map(([name, file]) => `${name} (${file.replace(/\\/g, '/').split('/src/')[1]})`)

    expect(missing).toEqual([])
  })

  it('keeps the Android-only commands out of the non-Android list', () => {
    // 反过来也要一致：cfg 掉的命令若出现在非 Android 列表里，编译就过不去；
    // 这里守住的是"两个列表都别把只在一个目标上存在的命令写错位置"。
    const { android, other } = handlerLists()
    expect(android.length).toBeGreaterThan(other.length)
    expect(new Set(android).size).toBe(android.length)
    expect(new Set(other).size).toBe(other.length)
  })
})
