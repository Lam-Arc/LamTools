import { getVersion } from '@tauri-apps/api/app'

// Published beside the versioned Android APK by the website release process.
// GitHub's desktop release is a separate version stream.
export const MOBILE_UPDATE_MANIFEST = 'https://47.114.43.99.nip.io/downloads/mobile-update.json'

interface MobileUpdateManifest {
  version: string
  download_url: string
  release_notes?: string
  release_url?: string
}

/** Manual update check against the mobile release stream. */
export async function checkStandaloneUpdate(installedVersion?: string): Promise<Record<string, unknown>> {
  const currentVersion = installedVersion || await getVersion()
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 10_000)
    let response: Response
    try {
      response = await fetch(MOBILE_UPDATE_MANIFEST, {
        headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller.signal,
      })
    } catch (error) {
      // Whether the network is down or the request timed out, the user needs the
      // address that failed to reach anyone who can fix it.
      const reason = error instanceof Error ? error.message : String(error)
      throw new Error(`移动版发布清单不可达：${MOBILE_UPDATE_MANIFEST}（${reason}）`)
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
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw manifestError('移动版发布清单格式错误')
    }
    const manifest = parsed as Partial<MobileUpdateManifest>
    const latestVersion = String(manifest.version || '').trim().replace(/^v/i, '')
    const downloadUrl = String(manifest.download_url || '')
    if (!/^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/.test(latestVersion)) throw manifestError('移动版发布清单版本号无效')
    if (!isHttpsUrl(downloadUrl)) throw manifestError('移动版发布清单下载地址无效')
    const releaseUrl = String(manifest.release_url || '')
    if (releaseUrl && !isHttpsUrl(releaseUrl)) throw manifestError('移动版发布清单发布地址无效')
    return {
      status: compareVersion(currentVersion, latestVersion) < 0 ? 'update_available' : 'up_to_date',
      current_version: currentVersion,
      latest_version: latestVersion,
      release_notes: String(manifest.release_notes || '').slice(0, 800),
      download_url: downloadUrl,
      release_url: releaseUrl,
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

function compareVersion(left: string, right: string): number {
  const a = left.match(/\d+/g)?.map(Number) || []
  const b = right.match(/\d+/g)?.map(Number) || []
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) - (b[i] || 0)
  }
  return 0
}
