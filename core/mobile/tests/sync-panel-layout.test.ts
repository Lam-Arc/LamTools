import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/** Only the component's own style block participates in the contract. */
const source = (readFileSync(resolve(import.meta.dirname, '../src/sync/MobileSyncPanel.vue'), 'utf8')
  .split('<style scoped>')[1] ?? '')
  .replace(/\/\*[\s\S]*?\*\//g, '')

/**
 * Every declaration block whose selector list contains `selector`, joined. A
 * selector can legitimately own several blocks (an element rule and a shared
 * list rule), so the contract is checked against all of them.
 */
function rules(selector: string): string {
  const bodies: string[] = []
  for (const match of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = match[1].split(',').map((part) => part.trim().replace(/\s+/g, ' '))
    if (selectors.includes(selector)) bodies.push(match[2])
  }
  expect(bodies.length, `missing CSS rule for ${selector}`).toBeGreaterThan(0)
  return bodies.join('\n')
}

/**
 * A device's project list is the one place in this sheet with unbreakable text
 * (a `workRoot` path). Its intrinsic width used to size the overlay's implicit
 * track, so the sheet grew wider than the screen instead of wrapping the path.
 */
describe('mobile sync panel layout', () => {
  it('keeps the sheet inside the viewport whatever the project rows contain', () => {
    expect(rules('.sync-overlay')).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/)
    expect(rules('.sync-panel')).toMatch(/width:\s*100%/)
    expect(rules('.sync-panel')).toMatch(/max-width:\s*620px/)
    expect(rules('.sync-panel')).toMatch(/min-width:\s*0/)
    expect(rules('.sync-body')).toMatch(/min-width:\s*0/)
    expect(rules('.sync-device-list')).toMatch(/min-width:\s*0/)
  })

  it('lets a project row shrink below the width of its own text', () => {
    expect(rules('.sync-device')).toMatch(/min-width:\s*0/)
    expect(rules('.sync-device > span')).toMatch(/min-width:\s*0/)
  })

  it('wraps the path and explanation line instead of stretching the card', () => {
    const small = rules('small')
    expect(small).toMatch(/overflow-wrap:\s*anywhere/)
    expect(small).not.toMatch(/white-space:\s*nowrap/)
    expect(small).not.toMatch(/text-overflow:\s*ellipsis/)
  })

  it('keeps names on one ellipsised line', () => {
    const strong = rules('strong')
    expect(strong).toMatch(/white-space:\s*nowrap/)
    expect(strong).toMatch(/text-overflow:\s*ellipsis/)
    expect(strong).toMatch(/overflow:\s*hidden/)
  })
})
