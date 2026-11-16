import { describe, expect, it } from 'vitest'
import { collectUiPaths } from '../../../scripts/ui-inventory.mjs'
import manifest from '../src/design-system/component-inventory.json'

describe('gallery inventory freshness', () => {
  it('covers all Vue files in the indexed Sunday desktop and bundled plugin sources', async () => {
    const actual = (await collectUiPaths()).filter((path: string) => path.endsWith('.vue')).sort()
    expect(manifest.map(item => item.path).sort()).toEqual(actual)
  })
})
