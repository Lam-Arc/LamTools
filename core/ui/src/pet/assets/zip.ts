/**
 * `.sundaypet`（ZIP 容器）导入。
 *
 * user:“支持安装/打开 .sundaypet（ZIP 包或正式采用的等效容器），打包不会改变原模型语义”+
 * (解包只在内存里做；每个条目都要过同一套路径/类型/体积校验，落盘交给 Rust 的
 *  单文件写入命令，普通资源包永远不执行脚本。)
 */
import { unzipSync } from 'fflate'
import { isRelativeSafePath } from './importer.ts'

export const MAX_ZIP_BYTES = 80 * 1024 * 1024
export const MAX_UNPACKED_BYTES = 200 * 1024 * 1024
export const MAX_ENTRIES = 800

/** 与 Rust `ALLOWED_ASSET_EXTS` 保持一致；脚本类扩展一律不在其中。 */
const ALLOWED_EXTS = new Set([
  'json', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg', 'glb', 'gltf', 'bin', 'atlas',
  'txt', 'md', 'ogg', 'mp3', 'wav', 'vrm', 'vrma', 'inp', 'inp2d', 'plist', 'skel', 'spriteatlas',
])

export interface ZipEntry {
  rel: string
  bytes: Uint8Array
}

export interface ZipImportResult {
  entries: ZipEntry[]
  /** 用于预览与持久化的相对路径表。 */
  map: Map<string, Uint8Array>
  errors: string[]
  warnings: string[]
  totalBytes: number
}

function extOf(rel: string): string {
  const match = /\.([a-z0-9]+)$/i.exec(rel)
  return match ? match[1].toLowerCase() : ''
}

/**
 * 解包并校验。返回的 rel 已经去掉容器里的公共顶层目录，
 * 这样 `MyPet/pet.json` 与 `pet.json` 两种打包方式都能用。
 */
export function readSundayPetZip(buffer: ArrayBuffer | Uint8Array): ZipImportResult {
  const errors: string[] = []
  const warnings: string[] = []
  const raw = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer)
  if (raw.byteLength === 0) {
    return { entries: [], map: new Map(), errors: ['角色包是空文件'], warnings, totalBytes: 0 }
  }
  if (raw.byteLength > MAX_ZIP_BYTES) {
    return {
      entries: [],
      map: new Map(),
      errors: [`角色包超过 ${Math.round(MAX_ZIP_BYTES / 1024 / 1024)}MB，已拒绝`],
      warnings,
      totalBytes: 0,
    }
  }
  let unpacked: Record<string, Uint8Array>
  try {
    unpacked = unzipSync(raw)
  } catch (error) {
    return {
      entries: [],
      map: new Map(),
      errors: [`不是有效的 ZIP 容器：${error instanceof Error ? error.message : String(error)}`],
      warnings,
      totalBytes: 0,
    }
  }

  const names = Object.keys(unpacked).filter(name => !name.endsWith('/'))
  if (names.length === 0) {
    return { entries: [], map: new Map(), errors: ['角色包里没有文件'], warnings, totalBytes: 0 }
  }
  if (names.length > MAX_ENTRIES) {
    errors.push(`角色包文件数 ${names.length} 超过上限 ${MAX_ENTRIES}`)
  }

  // 去掉公共顶层目录：aaa/pet.json + aaa/idle.png → pet.json + idle.png
  const prefix = commonPrefix(names)
  const entries: ZipEntry[] = []
  const map = new Map<string, Uint8Array>()
  let totalBytes = 0
  for (const name of names) {
    const rel = prefix ? name.slice(prefix.length) : name
    if (!rel) continue
    if (rel.startsWith('__MACOSX/') || rel.startsWith('.')) {
      warnings.push(`忽略打包噪音：${name}`)
      continue
    }
    if (!isRelativeSafePath(rel)) {
      errors.push(`路径不安全，已跳过：${name}`)
      continue
    }
    if (!ALLOWED_EXTS.has(extOf(rel))) {
      warnings.push(`不支持的文件类型，已跳过：${name}`)
      continue
    }
    const bytes = unpacked[name]
    totalBytes += bytes.byteLength
    if (totalBytes > MAX_UNPACKED_BYTES) {
      return {
        entries: [],
        map: new Map(),
        errors: [`解包后体积超过 ${Math.round(MAX_UNPACKED_BYTES / 1024 / 1024)}MB，已中止`],
        warnings,
        totalBytes,
      }
    }
    entries.push({ rel, bytes })
    map.set(rel, bytes)
  }

  if (entries.length === 0) errors.push('角色包里没有可用资源（类型都不在白名单内）')
  return { entries, map, errors, warnings, totalBytes }
}

function commonPrefix(names: string[]): string {
  const parts = names.map(name => name.split('/'))
  if (parts.some(entry => entry.length < 2)) return ''
  const first = parts[0][0]
  if (!parts.every(entry => entry[0] === first)) return ''
  // 只有**所有**文件都在同一个顶层目录里时才剥掉它。
  return `${first}/`
}

/** 角色包名字：优先 pet.json 里的 name，其次文件名。 */
export function packNameFrom(pathOrFile: string, manifestName?: string): string {
  if (manifestName && manifestName.trim()) return manifestName.trim()
  const base = pathOrFile.split(/[\\/]/).pop() || 'pet'
  return base.replace(/\.(sundaypet|zip)$/i, '').trim() || 'pet'
}
