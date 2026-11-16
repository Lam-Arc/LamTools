import { describe, expect, it } from 'vitest'
import * as importer from '../src/pet/assets/importer'

describe('pet asset limits used by editors', () => {
  it('exposes finite limits compatible with the desktop pack writer', () => {
    expect(importer.MAX_SCAN_FILES).toBe(800)
    expect(importer.MAX_SCAN_BYTES).toBe(160 * 1024 * 1024)
    expect(importer.MAX_ASSET_BYTES).toBe(64 * 1024 * 1024)
    expect(importer.MAX_IMAGE_EDGE).toBeGreaterThanOrEqual(4096)
  })
})
