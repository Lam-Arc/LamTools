/**
 * Update-check state for the "关于与更新" settings section.
 *
 * The check itself runs on the backend (`update.check` RPC — the official
 * site manifest first, GitHub Releases as the fallback, compared against
 * `lamtools_core.__version__`); this composable only drives the UI state
 * machine around it, so it stays pure and testable with a fake `requestRpc`.
 *
 * Install is intentionally *not* automated: the settings section hands the
 * user a download link (system browser → setup.exe), who runs it manually.
 */

import { computed, ref } from 'vue'
import { getAppVersion, openUpdatePage } from '../helpers/update'

export type CoreUpdateStatus = 'idle' | 'checking' | 'update_available' | 'up_to_date' | 'check_failed'

export interface CoreUpdateCheckPayload {
  status?: string
  current_version?: string
  latest_version?: string
  release_notes?: string
  download_url?: string
  release_url?: string
  /** Which source answered: 'site' (official manifest) or 'github'. */
  source?: string
  /** Which source supplied the release notes (may differ from `source`). */
  notes_source?: string
  /** Set when nothing installable exists for this platform (e.g. 'no_installer_for_platform'). */
  reason?: string
  error?: string
}

export type CoreUpdateRequestRpc = (method: string, params?: Record<string, unknown>) => Promise<unknown>

const AUTO_CHECK_STORAGE_KEY = 'lamtools.update.autoCheck'

/** Whether the app should silently check for updates on startup (persisted). */
export function readUpdateAutoCheck(): boolean {
  try {
    const raw = localStorage.getItem(AUTO_CHECK_STORAGE_KEY)
    if (raw === null) return true // default: enabled
    return raw !== 'false'
  } catch {
    return true
  }
}

export function setUpdateAutoCheck(enabled: boolean): void {
  try {
    localStorage.setItem(AUTO_CHECK_STORAGE_KEY, String(enabled))
  } catch {
    // storage unavailable — preference just does not persist
  }
}

export function useCoreUpdateState(requestRpc: CoreUpdateRequestRpc) {
  const status = ref<CoreUpdateStatus>('idle')
  const currentVersion = ref(getAppVersion())
  const latestVersion = ref('')
  const releaseNotes = ref('')
  const downloadUrl = ref('')
  const releaseUrl = ref('')
  const source = ref('')
  const reason = ref('')
  const error = ref('')

  /** Run `update.check` through the injected RPC channel and fold the result into state. */
  async function check(): Promise<void> {
    status.value = 'checking'
    error.value = ''
    try {
      const raw = (await requestRpc('update.check', {})) as CoreUpdateCheckPayload | null | undefined
      const payload = (raw ?? {}) as CoreUpdateCheckPayload
      const resultStatus = payload.status || 'check_failed'
      if (payload.current_version) currentVersion.value = payload.current_version
      if (payload.latest_version) latestVersion.value = payload.latest_version
      source.value = payload.source || ''
      reason.value = payload.reason || ''
      if (resultStatus === 'update_available') {
        status.value = 'update_available'
        releaseNotes.value = payload.release_notes || ''
        downloadUrl.value = payload.download_url || ''
        releaseUrl.value = payload.release_url || ''
      } else if (resultStatus === 'up_to_date') {
        status.value = 'up_to_date'
        releaseNotes.value = ''
        downloadUrl.value = ''
        releaseUrl.value = ''
      } else {
        status.value = 'check_failed'
        error.value = payload.error || '检查更新失败'
      }
    } catch (err) {
      status.value = 'check_failed'
      source.value = ''
      reason.value = ''
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Open the installer download in the system browser. Returns false when no URL is available. */
  async function download(): Promise<boolean> {
    return openUpdatePage(downloadUrl.value || releaseUrl.value)
  }

  /** Human-readable label for whichever source answered the last check. */
  const sourceLabel = computed(() => {
    if (source.value === 'site') return '官网'
    if (source.value === 'github') return 'GitHub Releases'
    return ''
  })

  /** 有新版本、但没有任何可用安装包（本平台）：文案不能说成"已是最新"。 */
  const noInstallerForPlatform = computed(() => reason.value === 'no_installer_for_platform')

  return {
    status,
    currentVersion,
    latestVersion,
    releaseNotes,
    downloadUrl,
    releaseUrl,
    source,
    sourceLabel,
    reason,
    noInstallerForPlatform,
    error,
    check,
    download,
  }
}

export type CoreUpdateState = ReturnType<typeof useCoreUpdateState>
