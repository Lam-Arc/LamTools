import { strFromU8, strToU8, unzipSync, zipSync } from 'fflate'
import type { StudioDocument } from './schema.ts'
import { THEME_STUDIO_SCHEMA_VERSION } from './schema.ts'
import { migrateStudioDocument } from './migrate.ts'
import { validateStudioDocument } from './validate.ts'

/**
 * 主题包：`.sunday-theme` 是一个 ZIP，装清单、文档和素材原件。
 *
 * user:“采用版本化主题包（如 .sunday-theme / ZIP + manifest + assets），
 * 包括 schemaVersion、资源哈希、预设和布局配置，不含会话正文、密钥、
 * 用户绝对路径或任意脚本。导入时先隔离解包与验证，允许预览，不直接覆盖现行主题。”+
 * (文档里只留素材引用与哈希，素材字节单独成文件；导入先校验再进草稿。)
 */

export const THEME_PACKAGE_FORMAT = 'sunday-theme'
export const THEME_PACKAGE_EXTENSION = '.sunday-theme'
export const THEME_PACKAGE_MANIFEST = 'manifest.json'
export const THEME_PACKAGE_DOCUMENT = 'document.json'
/** 整包上限：主题是界面配置，不该是几 MB 的相册。 */
export const THEME_PACKAGE_MAX_BYTES = 8 * 1024 * 1024
export const THEME_PACKAGE_MAX_ASSET_BYTES = 2 * 1024 * 1024
export const THEME_PACKAGE_MAX_ASSETS = 32

export interface ThemePackageAsset {
  id: string
  path: string
  sha256: string
  mime: string
  bytes: number
}

export interface ThemePackageManifest {
  format: typeof THEME_PACKAGE_FORMAT
  schemaVersion: number
  exportedAt: string
  assets: ThemePackageAsset[]
}

export interface ThemePackage {
  manifest: ThemePackageManifest
  document: StudioDocument
}

export class ThemePackageError extends Error {
  constructor(message: string, readonly code: 'invalid' | 'unsupported' | 'unsafe' | 'too-large' | 'corrupt') {
    super(message)
    this.name = 'ThemePackageError'
  }
}

const MIME_EXTENSION: Record<string, string> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/gif': 'gif',
  'image/webp': 'webp',
  'image/svg+xml': 'svg',
}

const EXTENSION_MIME: Record<string, string> = Object.fromEntries(
  Object.entries(MIME_EXTENSION).map(([mime, extension]) => [extension, mime]),
)

const DATA_URL = /^data:([^;,]+)?(;base64)?,([\s\S]*)$/

function base64ToBytes(payload: string): Uint8Array {
  const binary = globalThis.atob(payload)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunk = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk))
  }
  return globalThis.btoa(binary)
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const subtle = globalThis.crypto?.subtle
  // 没有 WebCrypto 的环境（极少数 WebView）降级为不校验哈希：包仍可用，只是少一层防篡改。
  if (!subtle) return ''
  const digest = await subtle.digest('SHA-256', bytes as unknown as BufferSource)
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

/** 素材在包里按 MIME 决定扩展名；未知类型直接拒绝，避免塞进任意文件。 */
function assetPathFor(assetId: string, mime: string): string {
  const extension = MIME_EXTENSION[mime]
  if (!extension) throw new ThemePackageError(`不支持的素材类型：${mime || '未知'}`, 'invalid')
  return `assets/${assetId}.${extension}`
}

function cloneDocument(document: StudioDocument): StudioDocument {
  return JSON.parse(JSON.stringify(document)) as StudioDocument
}

/**
 * 打包：文档里的素材字节拆成独立文件，document.json 只留引用。
 * 返回的字节可以直接下载成 `.sunday-theme`。
 */
export async function buildThemePackage(
  document: StudioDocument,
  at: Date = new Date(),
): Promise<Uint8Array> {
  const assets = document.assets || []
  if (assets.length > THEME_PACKAGE_MAX_ASSETS) {
    throw new ThemePackageError(`素材过多：最多 ${THEME_PACKAGE_MAX_ASSETS} 个`, 'too-large')
  }
  // 体积先于结构校验：超大素材要给「太大」这个明确原因，而不是一条泛泛的校验失败。
  for (const asset of assets) {
    const match = typeof asset.url === 'string' ? DATA_URL.exec(asset.url) : null
    if (match && base64ToBytes(match[3]).byteLength > THEME_PACKAGE_MAX_ASSET_BYTES) {
      throw new ThemePackageError(`素材过大：${asset.id}`, 'too-large')
    }
  }
  const validation = validateStudioDocument(document)
  if (!validation.ok) {
    throw new ThemePackageError(validation.errors[0]?.message || '主题文档校验未通过', 'invalid')
  }

  const files: Record<string, Uint8Array> = {}
  const manifestAssets: ThemePackageAsset[] = []
  const stripped = cloneDocument(document)
  stripped.assets = []

  for (const asset of assets) {
    const match = typeof asset.url === 'string' ? DATA_URL.exec(asset.url) : null
    if (!match) throw new ThemePackageError(`素材缺少可打包的内容：${asset.id}`, 'invalid')
    const mime = (match[1] || asset.mime || '').toLowerCase()
    if (mime !== asset.mime.toLowerCase()) {
      throw new ThemePackageError(`素材类型与声明不一致：${asset.id}`, 'invalid')
    }
    const bytes = base64ToBytes(match[3])
    if (bytes.byteLength > THEME_PACKAGE_MAX_ASSET_BYTES) {
      throw new ThemePackageError(`素材过大：${asset.id}`, 'too-large')
    }
    const path = assetPathFor(asset.id, mime)
    files[path] = bytes
    manifestAssets.push({
      id: asset.id,
      path,
      sha256: await sha256Hex(bytes),
      mime,
      bytes: bytes.byteLength,
    })
    stripped.assets.push({
      id: asset.id,
      sha256: asset.sha256,
      mime: asset.mime,
      width: asset.width,
      height: asset.height,
      url: '',
    })
  }

  const manifest: ThemePackageManifest = {
    format: THEME_PACKAGE_FORMAT,
    schemaVersion: THEME_STUDIO_SCHEMA_VERSION,
    exportedAt: at.toISOString(),
    assets: manifestAssets,
  }
  files[THEME_PACKAGE_MANIFEST] = strToU8(JSON.stringify(manifest, null, 2))
  files[THEME_PACKAGE_DOCUMENT] = strToU8(JSON.stringify(stripped, null, 2))
  const zipped = zipSync(files, { level: 6 })
  if (zipped.byteLength > THEME_PACKAGE_MAX_BYTES) {
    throw new ThemePackageError('主题包超过 8MB 上限', 'too-large')
  }
  return zipped
}

/** 路径安全：只接受包内相对路径，拒绝绝对路径与任何向上穿越。 */
function assertSafeEntry(name: string): void {
  const normalized = name.replace(/\\/g, '/')
  if (!normalized || normalized.startsWith('/') || /^[A-Za-z]:/.test(normalized)) {
    throw new ThemePackageError(`主题包含非法路径：${name}`, 'unsafe')
  }
  const parts = normalized.split('/')
  if (parts.some((part) => part === '..' || part === '.')) {
    throw new ThemePackageError(`主题包含越界路径：${name}`, 'unsafe')
  }
}

/**
 * 解包并校验：清单、版本、素材哈希、文档结构任何一项不过都拒绝。
 * 返回的是可以直接进草稿的文档（素材已还原成内嵌 data URL）。
 */
export async function readThemePackage(bytes: Uint8Array): Promise<ThemePackage> {
  if (bytes.byteLength > THEME_PACKAGE_MAX_BYTES) {
    throw new ThemePackageError('主题包超过 8MB 上限', 'too-large')
  }
  let files: Record<string, Uint8Array>
  try {
    files = unzipSync(bytes)
  } catch {
    throw new ThemePackageError('不是有效的主题包（ZIP 解包失败）', 'corrupt')
  }
  for (const name of Object.keys(files)) assertSafeEntry(name)
  if (!files[THEME_PACKAGE_MANIFEST] || !files[THEME_PACKAGE_DOCUMENT]) {
    throw new ThemePackageError('主题包缺少清单或文档', 'invalid')
  }

  let manifest: ThemePackageManifest
  let rawDocument: unknown
  try {
    manifest = JSON.parse(strFromU8(files[THEME_PACKAGE_MANIFEST])) as ThemePackageManifest
    rawDocument = JSON.parse(strFromU8(files[THEME_PACKAGE_DOCUMENT]))
  } catch {
    throw new ThemePackageError('主题包的清单或文档不是合法 JSON', 'corrupt')
  }
  if (!manifest || manifest.format !== THEME_PACKAGE_FORMAT) {
    throw new ThemePackageError('不是 Sunday 主题包', 'invalid')
  }
  if (manifest.schemaVersion !== THEME_STUDIO_SCHEMA_VERSION) {
    throw new ThemePackageError(
      `主题包版本 ${manifest.schemaVersion} 与当前版本 ${THEME_STUDIO_SCHEMA_VERSION} 不兼容`,
      'unsupported',
    )
  }
  const assets = Array.isArray(manifest.assets) ? manifest.assets : []
  if (assets.length > THEME_PACKAGE_MAX_ASSETS) {
    throw new ThemePackageError(`素材过多：最多 ${THEME_PACKAGE_MAX_ASSETS} 个`, 'too-large')
  }

  const declared = new Map<string, { width?: number; height?: number }>()
  for (const item of (rawDocument as { assets?: Array<{ id?: unknown; width?: unknown; height?: unknown }> }).assets || []) {
    if (!item || typeof item.id !== 'string') continue
    declared.set(item.id, { width: Number(item.width) || 0, height: Number(item.height) || 0 })
  }

  const restored: Array<{ id: string; sha256: string; mime: string; width: number; height: number; url: string }> = []
  for (const asset of assets) {
    if (!asset || typeof asset.id !== 'string' || typeof asset.path !== 'string') {
      throw new ThemePackageError('清单里的素材条目无效', 'invalid')
    }
    assertSafeEntry(asset.path)
    const data = files[asset.path]
    if (!data) throw new ThemePackageError(`主题包缺少素材：${asset.id}`, 'corrupt')
    if (data.byteLength > THEME_PACKAGE_MAX_ASSET_BYTES) {
      throw new ThemePackageError(`素材过大：${asset.id}`, 'too-large')
    }
    if (typeof asset.bytes === 'number' && asset.bytes !== data.byteLength) {
      throw new ThemePackageError(`素材大小与清单不一致：${asset.id}`, 'corrupt')
    }
    const hash = await sha256Hex(data)
    if (asset.sha256 && hash && asset.sha256 !== hash) {
      throw new ThemePackageError(`素材哈希不匹配：${asset.id}`, 'corrupt')
    }
    const mime = (asset.mime || EXTENSION_MIME[asset.path.split('.').pop()?.toLowerCase() || ''] || '').toLowerCase()
    if (!MIME_EXTENSION[mime]) throw new ThemePackageError(`不支持的素材类型：${mime || '未知'}`, 'invalid')
    const size = declared.get(asset.id) || {}
    restored.push({
      id: asset.id,
      // 文档里原来的摘要优先，其次才是这次算出来的；都没有就留空（校验会拦住）。
      sha256: String((rawDocument as { assets?: Array<{ id: string; sha256?: string }> }).assets?.find((item) => item.id === asset.id)?.sha256 || hash),
      mime,
      width: Number(size.width) || 0,
      height: Number(size.height) || 0,
      url: `data:${mime};base64,${bytesToBase64(data)}`,
    })
  }

  const migrated = migrateStudioDocument(rawDocument)
  if (!migrated.ok) throw new ThemePackageError(migrated.error || '主题文档无法迁移', 'invalid')
  const document = migrated.document
  document.assets = restored
  const validation = validateStudioDocument(document)
  if (!validation.ok) {
    throw new ThemePackageError(validation.errors[0]?.message || '主题文档校验未通过', 'invalid')
  }
  return { manifest, document }
}

/** 判断一份字节是不是 ZIP（主题包）；否则按旧版 JSON 文档处理。 */
export function looksLikeThemePackage(bytes: Uint8Array): boolean {
  return bytes.byteLength >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b
}

/** 旧版单文件 JSON：保留兼容，不因为升级导入就把人挡在门外。 */
export function readThemeDocumentJson(text: string): StudioDocument {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    throw new ThemePackageError('不是合法 JSON', 'corrupt')
  }
  const migrated = migrateStudioDocument(raw)
  if (!migrated.ok) throw new ThemePackageError(migrated.error || '主题文档无法迁移', 'invalid')
  const validation = validateStudioDocument(migrated.document)
  if (!validation.ok) {
    throw new ThemePackageError(validation.errors[0]?.message || '主题文档校验未通过', 'invalid')
  }
  return migrated.document
}
