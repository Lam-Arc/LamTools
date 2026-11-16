// @vitest-environment node
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { analyzeSource, collectUiPaths, componentImports, renderComponentIndex } from '../../../scripts/ui-inventory.mjs'
import manifest from '../src/design-system/component-inventory.json'

describe('component catalog metadata', () => {
  it('matches current source clues and references', async () => {
    const root = resolve(import.meta.dirname, '../../..')
    const paths = await collectUiPaths()
    const files = await Promise.all(paths.map(async (path: string) => {
      const source = await readFile(resolve(root, path), 'utf8')
      return { ...analyzeSource(path, source), imports: componentImports(path, source) }
    }))
    files.sort((a, b) => a.path.localeCompare(b.path, 'en'))
    expect(manifest).toEqual(renderComponentIndex(files))
  })
})
