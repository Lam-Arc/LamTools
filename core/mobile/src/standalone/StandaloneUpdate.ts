import { getVersion } from '@tauri-apps/api/app'
import { invoke } from '@tauri-apps/api/core'
import { hasEmbeddedRustCore } from '../native/rustAgent'

// Published beside the versioned Android APK by the website release process.
// GitHub's desktop release is a separate version stream.
export const MOBILE_UPDATE_MANIFEST = 'https://47.114.43.99.nip.io/downloads/mobile-update.json'

interface MobileUpdateManifest {
  version: string
  download_url: string
  release_notes?: string
  release_url?: string
  /** Digest of the APK the download URL serves; the host verifies against it. */
  sha256?: string
  size?: number
}

/**
 * True where this build can download, verify and hand an APK to the installer.
 *
 * The install hand-off is the Android shell's: the web build has no package
 * installer, and the desktop shell has its own update path.
 */
function canInstallInApp(): boolean {
  return hasEmbeddedRustCore()
    && typeof navigator !== 'undefined'
    && /android/i.test(navigator.userAgent)
}

/**
 * Read the manifest, through the host when the app runs in its Tauri shell.
 *
 * The WebView origin (`https://tauri.localhost`) is cross-origin to the release
 * site, so a `fetch` from here only works while the site happens to send
 * `Access-Control-Allow-Origin` — and a missing header arrives as a bare
 * `Failed to fetch` that names neither the status nor the cause. The host asks
 * over its own HTTP stack and reports the real status, so the app asks it first
 * and keeps the fetch below for the browser build only.
 */
async function readUpdateManifest(): Promise<Partial<MobileUpdateManifest>> {
  if (hasEmbeddedRustCore()) {
    let payload: unknown
    try {
      payload = await invoke<unknown>('sunday_update_manifest', { url: MOBILE_UPDATE_MANIFEST })
    } catch (error) {
      throw unreachableError(error)
    }
    return validateManifestPayload(payload)
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10_000)
  let response: Response
  try {
    response = await fetch(MOBILE_UPDATE_MANIFEST, {
      headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller.signal,
    })
  } catch (error) {
    throw unreachableError(error)
  } finally {
    clearTimeout(timer)
  }
  if (!response.ok) throw manifestError(`移动版发布清单 HTTP ${response.status}`)
  let parsed: unknown
  try {
    parsed = await response.json()
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    throw new Error(`移动版发布清单不是有效的 JSON：${MOBILE_UPDATE_MANIFEST}（${reason}）`)
  }
  return validateManifestPayload(parsed)
}

/** Name the address and the reason: this is what an on-device report can act on. */
function unreachableError(error: unknown): Error {
  const reason = error instanceof Error ? error.message : String(error)
  return new Error(`移动版发布清单不可达：${MOBILE_UPDATE_MANIFEST}（${reason}）`)
}

function validateManifestPayload(parsed: unknown): Partial<MobileUpdateManifest> {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw manifestError('移动版发布清单格式错误')
  }
  return parsed as Partial<MobileUpdateManifest>
}

/** Manual update check against the mobile release stream. */
export async function checkStandaloneUpdate(installedVersion?: string): Promise<Record<string, unknown>> {
  const currentVersion = installedVersion || await getVersion()
  try {
    const manifest = await readUpdateManifest()
    const latestVersion = String(manifest.version || '').trim().replace(/^v/i, '')
    const downloadUrl = String(manifest.download_url || '')
    // 与桌面的 compare_versions 同口径：数字段可以是任意层（尾零按补零比较），
    // 允许预发布/构建后缀（0.1.31-beta.1）。原先只认三段，会把 0.1.30.0 这类
    // 写法直接判成"清单无效"，与桌面端行为不一致。
    if (!/^\d+(?:\.\d+)*(?:[-+][\w.-]+)?$/.test(latestVersion)) throw manifestError('移动版发布清单版本号无效')
    if (!isHttpsUrl(downloadUrl)) throw manifestError('移动版发布清单下载地址无效')
    const releaseUrl = String(manifest.release_url || '')
    if (releaseUrl && !isHttpsUrl(releaseUrl)) throw manifestError('移动版发布清单发布地址无效')
    // The digest is what the downloaded bytes are checked against before an
    // installer sees them, so an unusable one just means "no in-app install"
    // rather than a failed check.
    const digest = String(manifest.sha256 || '').trim().toLowerCase()
    const usableDigest = /^[0-9a-f]{64}$/.test(digest) ? digest : ''
    const installable = Boolean(usableDigest) && canInstallInApp()
    return {
      status: compareVersion(currentVersion, latestVersion) < 0 ? 'update_available' : 'up_to_date',
      current_version: currentVersion,
      latest_version: latestVersion,
      release_notes: String(manifest.release_notes || '').slice(0, 800),
      download_url: downloadUrl,
      release_url: releaseUrl,
      ...(usableDigest ? { sha256: usableDigest, size: Number(manifest.size) || 0 } : {}),
      install_supported: installable,
      ...(installable
        ? { install_hint: '点「立即安装」会把安装包交给系统安装器；首次需要在系统提示里允许 Sunday 安装应用。' }
        : {}),
    }
  } catch (error) {
    return { status: 'check_failed', current_version: currentVersion, error: error instanceof Error ? error.message : String(error) }
  }
}

/**
 * Name the address in every failure.
 *
 * For ten releases the only thing an on-device check could report was that the
 * manifest was unreadable, with nothing saying where the app had looked, so the
 * report could not be acted on without reading this file.
 */
function manifestError(message: string): Error {
  return new Error(`${message}：${MOBILE_UPDATE_MANIFEST}`)
}

function isHttpsUrl(value: string): boolean {
  try { return new URL(value).protocol === 'https:' }
  catch { return false }
}

/**
 * Version comparison shared in spirit with the desktop's
 * `lamtools_core.update.checker.compare_versions` — the two hosts must not
 * disagree about which of two versions is newer.
 *
 * Numeric cores are compared with the shorter one padded by zeros; a
 * pre-release (`-beta.1`) ranks *below* its release (`0.3.7-beta.1 < 0.3.7`),
 * and pre-release identifiers follow semver (numeric before alphanumeric,
 * numeric compared as numbers). Build metadata is ignored.
 */
function compareVersion(left: string, right: string): number {
  const split = (value: string): { numbers: number[]; identifiers: string[] } => {
    const text = String(value || '').trim().replace(/^v/i, '').split('+', 1)[0]
    const dash = text.indexOf('-')
    const core = dash >= 0 ? text.slice(0, dash) : text
    const pre = dash >= 0 ? text.slice(dash + 1) : ''
    const numbers = core.match(/\d+/g)?.map(Number) || [0]
    return { numbers, identifiers: pre ? pre.split('.').filter(Boolean) : [] }
  }
  const a = split(left)
  const b = split(right)
  for (let i = 0; i < Math.max(a.numbers.length, b.numbers.length); i += 1) {
    const x = a.numbers[i] || 0
    const y = b.numbers[i] || 0
    if (x !== y) return x < y ? -1 : 1
  }
  const aHasPre = a.identifiers.length > 0
  const bHasPre = b.identifiers.length > 0
  if (aHasPre !== bHasPre) return aHasPre ? -1 : 1   // 正式版 > 预发布
  if (aHasPre) {
    for (let i = 0; i < Math.max(a.identifiers.length, b.identifiers.length); i += 1) {
      const x = a.identifiers[i]
      const y = b.identifiers[i]
      if (x === undefined) return -1
      if (y === undefined) return 1
      const xNumeric = /^\d+$/.test(x)
      const yNumeric = /^\d+$/.test(y)
      if (xNumeric && yNumeric) {
        if (Number(x) !== Number(y)) return Number(x) < Number(y) ? -1 : 1
        continue
      }
      if (xNumeric !== yNumeric) return xNumeric ? -1 : 1   // 数字段 < 字母段
      if (x !== y) return x < y ? -1 : 1
    }
  }
  return 0
}
