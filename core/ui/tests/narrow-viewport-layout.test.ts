import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Narrow-viewport contracts.
 *
 * Every rule below exists because a phone (≤ 640px) clipped content or let one
 * box widen the whole column. jsdom has no layout engine, so these guard the
 * CSS contract that the browser-level audit established.
 */
const layout = readFileSync(resolve(import.meta.dirname, '../src/styles/layout.css'), 'utf8')
const workspaceShell = readFileSync(resolve(import.meta.dirname, '../src/styles/workspace-shell.css'), 'utf8')
const markdownRenderer = readFileSync(resolve(import.meta.dirname, '../src/components/MarkdownRenderer.vue'), 'utf8')
const chatThread = readFileSync(resolve(import.meta.dirname, '../src/components/ChatThread.vue'), 'utf8')

/** Slice one `@media (max-width: Npx) { … }` block, braces balanced. */
function mediaBlock(source: string, width: number): string {
  const start = source.indexOf(`@media (max-width: ${width}px) {`)
  expect(start, `missing @media (max-width: ${width}px)`).toBeGreaterThanOrEqual(0)
  let depth = 0
  for (let i = start; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    else if (source[i] === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start, i + 1)
    }
  }
  throw new Error(`unbalanced @media (max-width: ${width}px) block`)
}

/** Body of a single rule inside `block`, keyed by its exact selector. */
function ruleBody(block: string, selector: string): string {
  const escaped = selector
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\s+/g, '\\s+')
  const match = block.match(new RegExp(`${escaped}\\s*\\{([^{}]*)\\}`))
  expect(match, `missing CSS rule for ${selector}`).not.toBeNull()
  return match?.[1] ?? ''
}

describe('process stream stays inside the message column', () => {
  it('sizes its column so a wide tool card cannot push the message wider', () => {
    const stream = ruleBody(layout, '.process-stream')
    expect(stream).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/)
  })

  it('lets every process box shrink below its content', () => {
    expect(layout).toMatch(
      /\.process-stream,\s*\.process-stream > \*,[\s\S]{0,400}?\.process-group-body > \*,\s*\.process-step\s*\{\s*min-width:\s*0;\s*\}/,
    )
  })
})

describe('markdown tables on phones', () => {
  const mobile = mediaBlock(markdownRenderer, 640)

  it('pans natively instead of relying on the 12px scroll strip', () => {
    expect(ruleBody(mobile, '.markdown-body :deep(.markdown-table-viewport)')).toMatch(/overflow-x:\s*auto/)
    expect(ruleBody(mobile, '.markdown-body :deep(.markdown-table-scrollbar)')).toMatch(/display:\s*none/)
  })

  it('keeps the desktop branch clipped with its custom scrollbar', () => {
    expect(ruleBody(markdownRenderer, '.markdown-body :deep(.markdown-table-viewport)')).toMatch(/overflow-x:\s*clip/)
  })
})

describe('tool card content on phones', () => {
  it('wraps the block that has no wrap toggle of its own', () => {
    const rule = ruleBody(mediaBlock(chatThread, 640), '.tool-output')
    expect(rule).toMatch(/white-space:\s*pre-wrap/)
    expect(rule).toMatch(/word-break:\s*break-word/)
  })
})

describe('empty-session hero on phones', () => {
  const mobile = mediaBlock(layout, 640)

  it('floats above a bottom-anchored composer', () => {
    const rule = ruleBody(mobile, '.workspace-shell--composer-bottom .empty-session-hero')
    expect(rule).toMatch(/top:\s*auto/)
    expect(rule).toMatch(/bottom:\s*calc\([\s\S]*--composer-height/)
  })

  it('floats above the centred composer of a blank session', () => {
    const rule = ruleBody(mobile, '.workspace-shell--empty-session .empty-session-hero')
    expect(rule).toMatch(/top:\s*calc\(var\(--empty-session-composer-top/)
    expect(rule).toMatch(/bottom:\s*auto/)
    expect(rule).toMatch(/transform:\s*translate\(-50%,\s*-100%\)/)
  })
})

describe('settings sheet on phones', () => {
  it('lets the main pane take the rest of the page', () => {
    const rule = ruleBody(mediaBlock(layout, 719), '.settings-main')
    expect(rule).toMatch(/flex:\s*1 1 auto/)
  })
})

describe('keyboard clearance', () => {
  it('accepts an inset from a host whose window does not shrink with the keyboard', () => {
    const shell = ruleBody(workspaceShell, '.workspace-shell')
    expect(shell).toContain(
      'max(var(--keyboard-inset), var(--native-keyboard-inset, 0px), var(--safe-area-bottom))',
    )
  })

  it('caps a centred blank-session composer above whatever covers the bottom', () => {
    const centered = layout.match(
      /\.workspace-shell--empty-session\.workspace-shell--composer-center \{([\s\S]*?)\n\}/,
    )?.[1] ?? ''
    expect(centered).toMatch(/--empty-session-composer-top:\s*min\(/)
    expect(centered).toMatch(/var\(--composer-bottom-offset, 0px\)/)
    expect(centered).toMatch(/var\(--composer-clearance, 24px\)/)
  })
})

describe('mobile drawer scrim', () => {
  it('hides the empty-session hero while the rail is open', () => {
    const rule = ruleBody(mediaBlock(workspaceShell, 640), '.left-open .empty-session-hero')
    expect(rule).toMatch(/visibility:\s*hidden/)
  })
})
