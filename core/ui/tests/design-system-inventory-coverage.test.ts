import { describe, expect, it } from 'vitest'
import { collectUiPaths } from '../../../scripts/ui-inventory.mjs'

describe('Sunday inventory scope', () => {
  it('includes desktop entrypoints and bundled plugin UI, excluding unrelated projects', async () => {
    const paths: string[] = await collectUiPaths()
    expect(paths.some(path => path === 'core/desktop/src/main.ts')).toBe(true)
    expect(paths.some(path => path === 'core/desktop/index.html')).toBe(true)
    expect(paths.some(path => path.includes('plugins/bundled/workflow/ui/WorkflowView.vue'))).toBe(true)
    expect(paths.some(path => /^(website|plugins|ui-kit)\//.test(path))).toBe(false)
  })
})
