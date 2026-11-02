import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from 'vitest'

// user:“去除消息流左侧的竖线 层级关系不再用竖线表示 而是缩进，缩进 2px 即可”
// +(验收：消息流过程区与过程分组展开体都不再有左侧竖线，
//   层级只靠缩进表达，每层左缩进固定 2px。)

const layoutCss = readFileSync(resolve(import.meta.dirname, '../src/styles/layout.css'), 'utf8')
const processCss = readFileSync(resolve(import.meta.dirname, '../src/styles/chat-thread-process.css'), 'utf8')

function cssRule(source: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = source.match(new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\}`))
  expect(match, `missing CSS rule for ${selector}`).not.toBeNull()
  return match?.[1] || ''
}

test('消息流过程区去掉左侧竖线，改为 2px 缩进', () => {
  const rule = cssRule(layoutCss, '.process-stream')

  expect(rule).not.toContain('border-left')
  expect(rule).toMatch(/padding:\s*10px 0 10px 2px/)
})

test('过程分组展开体去掉左侧竖线，改为 2px 缩进', () => {
  const rule = cssRule(processCss, '.process-group-body')

  expect(rule).not.toContain('border-left')
  expect(rule).toMatch(/padding:\s*4px 0 4px 2px/)
})
