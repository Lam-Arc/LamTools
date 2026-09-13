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

test('markdown tables retain native layout and use a clipped outer viewport', () => {
  const card = cssRule('.markdown-body :deep(.markdown-table-shell)')
  const table = cssRule('.markdown-body :deep(table)')
  const viewport = cssRule('.markdown-body :deep(.markdown-table-viewport)')
  const header = cssRule('.markdown-body :deep(thead)')
  const scrollbar = cssRule('.markdown-body :deep(.markdown-table-scrollbar)')

  expect(table).not.toMatch(/display:\s*block/)
  expect(table).not.toMatch(/overflow-x:\s*auto/)
  expect(card).toMatch(/border-radius:\s*var\(--radius\)/)
  expect(card).not.toMatch(/box-shadow/)
  expect(viewport).toMatch(/overflow-x:\s*clip/)
  expect(viewport).toMatch(/overflow-y:\s*auto/)
  expect(viewport).toMatch(/max-height:\s*min\(60vh,\s*480px\)/)
  expect(header).toMatch(/position:\s*sticky/)
  expect(header).toMatch(/top:\s*0/)
  expect(scrollbar).toMatch(/position:\s*relative/)
  expect(scrollbar).not.toMatch(/position:\s*sticky/)
  expect(header).toMatch(/background:\s*var\(--theme-main-solid/)
  expect(scrollbar).toMatch(/background:\s*var\(--theme-main-solid/)
})
