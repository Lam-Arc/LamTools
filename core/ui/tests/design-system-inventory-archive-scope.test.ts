// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { collectUiPaths } from '../../../scripts/ui-inventory.mjs'

describe('desktop inventory scope', () => {
  it('excludes archived code and mobile-only entrypoints', async () => {
    const paths: string[] = await collectUiPaths()
    expect(paths.some(path => /\/archived\//i.test(path))).toBe(false)
    expect(paths.some(path => /\/(?:MobileTopBar\.vue|main-android\.ts)$/i.test(path))).toBe(false)
    expect(paths).toContain('core/desktop/src/main.ts')
  })
})
