// @vitest-environment node
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('full-area button reuse', () => {
  it('uses one scoped button recipe across task and scheduling pages', () => {
    const base = resolve(import.meta.dirname, '../src')
    for (const name of ['CoreSuperAgentPanel.vue', 'CoreArrangeManager.vue']) {
      const source = readFileSync(resolve(base, 'components', name), 'utf8')
      expect(source).toContain('styles/full-area-buttons.css')
      expect(source).not.toContain('.quiet-button.danger:hover:not(:disabled)')
    }
    const styles = readFileSync(resolve(base, 'styles/full-area-buttons.css'), 'utf8')
    expect(styles).toContain('.quiet-button.danger:hover:not(:disabled)')
    expect(styles).toContain('var(--theme-control-text)')
  })
})
