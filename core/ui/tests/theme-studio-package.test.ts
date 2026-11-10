import { describe, expect, it } from 'vitest'
import { strToU8, zipSync } from 'fflate'
import { createEmptyStudioDocument, type StudioDocument } from '../src/themeStudio/schema.ts'
import {
  THEME_PACKAGE_DOCUMENT,
  THEME_PACKAGE_MANIFEST,
  ThemePackageError,
  buildThemePackage,
  looksLikeThemePackage,
  readThemeDocumentJson,
  readThemePackage,
} from '../src/themeStudio/package.ts'

/**
 * user:“版本化主题包（.sunday-theme / ZIP + manifest + assets）”“导入时先隔离解包与验证”+
 * (文档与素材分开存，哈希对不上、路径越界、版本不兼容都要拒绝。)
 */

const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4])

function toDataUrl(bytes: Uint8Array): string {
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return `data:image/png;base64,${btoa(binary)}`
}

async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes as unknown as BufferSource)
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function documentWithAsset(): Promise<StudioDocument> {
  const document = createEmptyStudioDocument('studio')
  document.nodes['shell.sidebar'] = { spacing: { gap: 8 } }
  document.assets = [{
    id: 'asset-1',
    sha256: await sha256(PNG_BYTES),
    mime: 'image/png',
    width: 32,
    height: 64,
    url: toDataUrl(PNG_BYTES),
  }]
  return document
}

describe('主题包', () => {
  it('打包再解包，文档与素材都还原', async () => {
    const document = await documentWithAsset()
    const bytes = await buildThemePackage(document, new Date('2026-11-09T00:00:00Z'))
    expect(looksLikeThemePackage(bytes)).toBe(true)

    const parsed = await readThemePackage(bytes)
    expect(parsed.manifest.format).toBe('sunday-theme')
    expect(parsed.manifest.exportedAt).toBe('2026-11-09T00:00:00.000Z')
    expect(parsed.manifest.assets).toHaveLength(1)
    expect(parsed.manifest.assets[0].path).toBe('assets/asset-1.png')
    expect(parsed.manifest.assets[0].bytes).toBe(PNG_BYTES.byteLength)
    expect(parsed.document.nodes['shell.sidebar']?.spacing?.gap).toBe(8)
    expect(parsed.document.assets[0].url).toBe(toDataUrl(PNG_BYTES))
    expect(parsed.document.assets[0].width).toBe(32)
  })

  it('拒绝越界路径', async () => {
    const files = {
      [THEME_PACKAGE_MANIFEST]: strToU8(JSON.stringify({
        format: 'sunday-theme', schemaVersion: 1, exportedAt: new Date().toISOString(), assets: [],
      })),
      [THEME_PACKAGE_DOCUMENT]: strToU8(JSON.stringify(createEmptyStudioDocument('studio'))),
      '../evil.json': strToU8('{}'),
    }
    const bytes = zipSync(files)
    await expect(readThemePackage(bytes)).rejects.toBeInstanceOf(ThemePackageError)
    await expect(readThemePackage(bytes)).rejects.toMatchObject({ code: 'unsafe' })
  })

  it('拒绝不兼容的版本', async () => {
    const files = {
      [THEME_PACKAGE_MANIFEST]: strToU8(JSON.stringify({
        format: 'sunday-theme', schemaVersion: 99, exportedAt: new Date().toISOString(), assets: [],
      })),
      [THEME_PACKAGE_DOCUMENT]: strToU8(JSON.stringify(createEmptyStudioDocument('studio'))),
    }
    await expect(readThemePackage(zipSync(files))).rejects.toMatchObject({ code: 'unsupported' })
  })

  it('素材被改过就拒绝', async () => {
    const document = await documentWithAsset()
    const bytes = await buildThemePackage(document)
    // 直接把包里的素材字节换掉，哈希校验必须发现。
    const parsed = await readThemePackage(bytes)
    expect(parsed.document.assets).toHaveLength(1)

    const tampered = new Uint8Array([...PNG_BYTES, 9, 9, 9])
    const files = {
      [THEME_PACKAGE_MANIFEST]: strToU8(JSON.stringify({
        format: 'sunday-theme',
        schemaVersion: 1,
        exportedAt: new Date().toISOString(),
        assets: [{ id: 'asset-1', path: 'assets/asset-1.png', sha256: document.assets[0].sha256, mime: 'image/png', bytes: tampered.byteLength }],
      })),
      [THEME_PACKAGE_DOCUMENT]: strToU8(JSON.stringify(document)),
      'assets/asset-1.png': tampered,
    }
    await expect(readThemePackage(zipSync(files))).rejects.toMatchObject({ code: 'corrupt' })
  })

  it('超过单张素材上限就不打包', async () => {
    const document = createEmptyStudioDocument('studio')
    const huge = new Uint8Array(2 * 1024 * 1024 + 1)
    document.assets = [{
      id: 'asset-big',
      sha256: await sha256(huge),
      mime: 'image/png',
      width: 1,
      height: 1,
      url: toDataUrl(huge),
    }]
    await expect(buildThemePackage(document)).rejects.toMatchObject({ code: 'too-large' })
  })

  it('旧版单文件 JSON 仍可导入', () => {
    const document = createEmptyStudioDocument('studio')
    document.nodes['shell.sidebar'] = { spacing: { gap: 12 } }
    const restored = readThemeDocumentJson(JSON.stringify(document))
    expect(restored.nodes['shell.sidebar']?.spacing?.gap).toBe(12)

    expect(() => readThemeDocumentJson('{')).toThrow(ThemePackageError)
  })
})
