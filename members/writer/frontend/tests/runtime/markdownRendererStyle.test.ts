import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../../src/components/MarkdownRenderer.vue', import.meta.url), 'utf8')

function cssRule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = source.match(new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\}`))
  assert.ok(match, `missing CSS rule for ${selector}`)
  return match[1]
}

test('markdown blockquotes use theme text color instead of hard-coded light text', () => {
  const rule = cssRule('.markdown-body :deep(blockquote)')

  assert.match(rule, /color-mix\(in srgb,\s*var\(--theme-main-text/)
  assert.doesNotMatch(rule, /rgba\(255,\s*255,\s*255,\s*0\.[0-9]+\)/)
})
