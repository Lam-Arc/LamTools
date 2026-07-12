import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from 'vitest'

const source = readFileSync(resolve(import.meta.dirname, '../src/components/MarkdownRenderer.vue'), 'utf8')

function cssRule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = source.match(new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\}`))
  expect(match, `missing CSS rule for ${selector}`).not.toBeNull()
  return match?.[1] || ''
}

test('markdown blockquotes use theme text color instead of hard-coded light text', () => {
  const rule = cssRule('.markdown-body :deep(blockquote)')

  expect(rule).toMatch(/color-mix\(in srgb,\s*var\(--theme-main-text/)
  expect(rule).not.toMatch(/rgba\(255,\s*255,\s*255,\s*0\.[0-9]+\)/)
})
