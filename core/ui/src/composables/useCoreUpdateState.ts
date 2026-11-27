/**
 * Update-check state for the "关于与更新" settings section.
 *
 * The check itself runs on the backend (`update.check` RPC — the official
 * site manifest first, GitHub Releases as the fallback, compared against the
 * host's version); this composable drives the UI state machine around it, so it
 * stays pure and testable with a fake `requestRpc`.
 *
 * Installing stays a user decision on both platforms, but it no longer requires
 * a browser: when the manifest publishes a digest, the host downloads the
 * artifact, verifies it, and hands it to the platform's installer (Android's
 * package installer, the desktop setup.exe) — `update.download` and
 * `update.install`. Without a digest the section keeps the old link-out.
 *
 * The transfer belongs to the host, not to a card: closing the card leaves it
 * running (user：“更新时可以后台下载”), and the next open — or another click on
 * 更新 — adopts the same progress instead of starting over (user：“再次点更新键
 * 后的卡片继承进度”).
 */

import { computed, ref } from 'vue'
import { getAppVersion, openUpdatePage, quitApp } from '@/helpers/update.ts'

export type CoreUpdateStatus = 'idle' | 'checking' | 'update_available' | 'up_to_date' | 'check_failed'

/** Progress of the in-app download and the install hand-off. */
export type CoreUpdateInstallState = 'idle' | 'downloading' | 'downloaded' | 'installing'

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
  /**
   * Digest of the installer the manifest points at. A digest is what makes the
   * in-app path possible: it is the only thing the downloaded bytes can be
   * checked against before an installer is handed them.
   */
  sha256?: string
  size?: number
  /** True when this host can download, verify and hand the artifact to an installer. */
  install_supported?: boolean
  /** Platform-specific wording for what the install step does. */
  install_hint?: string
}

export type CoreUpdateRequestRpc = (method: string, params?: Record<string, unknown>) => Promise<unknown>

const AUTO_CHECK_STORAGE_KEY = 'lamtools.update.autoCheck'
/** How often the section asks the host how far the download has come. */
const DOWNLOAD_POLL_MS = 400
/** A 90 MB installer over a slow link still finishes inside this. */
const DOWNLOAD_TIMEOUT_MS = 30 * 60 * 1000

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
  const installSupported = ref(false)
  const installHint = ref('')
  const installState = ref<CoreUpdateInstallState>('idle')
  const installMessage = ref('')
  /** 这次下载实际走的出口：accelerator | proxy | configured | direct。 */
  const installRoute = ref('')
  const installError = ref('')
  const installProgress = ref<number | null>(null)
  const installReceived = ref(0)
  const installTotal = ref(0)
  const packageSize = ref(0)

  /** The single poll loop this state object runs; shared by every caller. */
  let watching: Promise<boolean> | null = null
  /** The in-flight `update.download` call, so a second click joins it. */
  let starting: Promise<boolean> | null = null

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
        installSupported.value = payload.install_supported === true
        installHint.value = payload.install_hint || ''
        packageSize.value = Number(payload.size || 0) || 0
      } else if (resultStatus === 'up_to_date') {
        status.value = 'up_to_date'
        releaseNotes.value = ''
        downloadUrl.value = ''
        releaseUrl.value = ''
        installSupported.value = false
        installHint.value = ''
        packageSize.value = 0
        // 已经在下载/安装时不回退这一侧的状态：并发的“检查更新”不该把正在跑的下载
        // 显示成还没开始。
        if (installState.value !== 'downloading' && installState.value !== 'installing') {
          installState.value = 'idle'
          installProgress.value = null
          installMessage.value = ''
        }
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

  /** Fold one `update.status` answer into the reactive fields. */
  function applyHostStatus(status: Record<string, unknown>): void {
    const received = Number(status.received || 0)
    const total = Number(status.total || 0)
    installReceived.value = Number.isFinite(received) && received > 0 ? received : 0
    installTotal.value = Number.isFinite(total) && total > 0 ? total : 0
    installProgress.value = installTotal.value > 0
      ? Math.min(1, installReceived.value / installTotal.value)
      : null
    installRoute.value = String(status.route || '')
    installMessage.value = String(status.message || '')
  }

  /**
   * Watch the transfer until it settles.
   *
   * One loop per state object: a reopened card or a second click joins this
   * promise instead of starting a parallel poll. `true` means the artifact is
   * downloaded and verified, `false` means cancelled (or the host forgot it).
   */
  function watchDownload(): Promise<boolean> {
    if (watching) return watching
    const task = (async (): Promise<boolean> => {
      const deadline = Date.now() + DOWNLOAD_TIMEOUT_MS
      for (;;) {
        const raw = (await requestRpc('update.status', {})) as Record<string, unknown> | null
        const status = (raw ?? {}) as Record<string, unknown>
        if (status.ok !== true) throw new Error(String(status.error || '无法读取下载进度'))
        applyHostStatus(status)
        const state = String(status.state || '')
        if (state === 'downloading') {
          installState.value = 'downloading'
          installError.value = ''
        } else if (state === 'verified') {
          installState.value = 'downloaded'
          installProgress.value = null
          if (!installMessage.value) installMessage.value = '安装包已下载并校验通过'
          return true
        } else if (state === 'cancelled') {
          // 取消是这条下载的正常结局之一：清干净进度，回到可以重新开始的状态，
          // 不当成错误（否则卡片会显示一句假的失败）。
          installState.value = 'idle'
          installProgress.value = null
          installReceived.value = 0
          installTotal.value = 0
          installMessage.value = ''
          return false
        } else if (state === 'failed') {
          throw new Error(String(status.error || '下载安装包失败'))
        } else {
          // 主机手里已经没有这条下载了（后端重启过）：别把卡片永远钉在“下载中”。
          installState.value = 'idle'
          installProgress.value = null
          return false
        }
        if (Date.now() > deadline) throw new Error('下载超时，请重试')
        await new Promise((resolve) => setTimeout(resolve, DOWNLOAD_POLL_MS))
      }
    })()
      .catch((err: unknown) => {
        installState.value = 'idle'
        installProgress.value = null
        installError.value = err instanceof Error ? err.message : String(err)
        return false
      })
      .finally(() => {
        if (watching === task) watching = null
      })
    watching = task
    return task
  }

  /**
   * Ask the host to download the artifact — or join the transfer it is already
   * running.
   *
   * user:“更新时可以后台下载。再次点更新键后的卡片继承进度”+(只有真正空闲时才开新的
   * 传输；卡片关掉后下载照旧，重新点“更新”接上的是同一条进度，不会从 0 重来。)
   *
   * The host owns the URL and the digest (it read the manifest), so this takes
   * no arguments, and it answers at once: a 60-95 MB transfer takes a while, so
   * progress comes from polling `update.status` instead of holding one call open.
   */
  function downloadInstaller(): Promise<boolean> {
    if (watching) return watching
    if (starting) return starting
    if (installState.value === 'installing') return Promise.resolve(false)
    // 这一侧已经显示“下载中”却没有轮询：进度是继承来的，只接轮询、不重开传输。
    if (installState.value === 'downloading') return watchDownload()
    installState.value = 'downloading'
    installMessage.value = ''
    installError.value = ''
    installProgress.value = null
    const begin = (async (): Promise<boolean> => {
      try {
        const started = (await requestRpc('update.download', {})) as Record<string, unknown> | null
        const start = (started ?? {}) as Record<string, unknown>
        if (start.ok !== true) throw new Error(String(start.error || '下载安装包失败'))
        // 主机可能已经在下载了（上一次点击、设置页开的）：它回的就是当前进度。
        applyHostStatus(start)
      } catch (err) {
        installState.value = 'idle'
        installProgress.value = null
        installError.value = err instanceof Error ? err.message : String(err)
        return false
      }
      return watchDownload()
    })()
    starting = begin
    void begin.finally(() => {
      if (starting === begin) starting = null
    })
    return begin
  }

  /**
   * Adopt whatever the host is already doing.
   *
   * user:“再次点更新键后的卡片继承进度”+(每次打开卡片先问一次主机：后台还在下就接上
   * 那条传输继续显示进度，已经下好就直接变成“立即安装”，上次失败就把原因带回来；
   * 不必再点一次“更新”，更不会从 0 重来。)
   */
  async function syncFromHost(): Promise<void> {
    if (installState.value === 'installing') return
    try {
      const raw = (await requestRpc('update.status', {})) as Record<string, unknown> | null
      const status = (raw ?? {}) as Record<string, unknown>
      if (status.ok !== true) return
      const state = String(status.state || '')
      if (state === 'downloading') {
        applyHostStatus(status)
        installState.value = 'downloading'
        installError.value = ''
        void watchDownload()
        return
      }
      if (state === 'verified') {
        applyHostStatus(status)
        installState.value = 'downloaded'
        installProgress.value = null
        if (!installMessage.value) installMessage.value = '安装包已下载并校验通过'
        return
      }
      if (state === 'failed') {
        installState.value = 'idle'
        installProgress.value = null
        installError.value = String(status.error || '下载安装包失败')
        return
      }
      // idle / cancelled：主机没在下载。这一侧若还挂着“下载中”就是过期状态
      // （后端重启过），回到 idle 而不是永远等一条不存在的传输。
      if (installState.value === 'downloading' && !watching) {
        installState.value = 'idle'
        installProgress.value = null
      }
    } catch {
      // 问不到进度不算错误：卡片照常显示这一侧已经知道的状态。
    }
  }

  /**
   * Cancel a running download.
   *
   * The host stops the transfer between chunks and reports 'cancelled', which the
   * polling loop above turns into a clean idle state. Cancelling when nothing is
   * running is a no-op, so a card can ask twice without an error.
   */
  async function cancelDownload(): Promise<boolean> {
    if (installState.value !== 'downloading') return false
    try {
      await requestRpc('update.cancel', {})
    } catch (err) {
      console.error('[update] cancel failed:', err)
    }
    return true
  }

  /** Hand the verified artifact to the platform's installer. */
  async function runInstaller(): Promise<boolean> {
    if (installState.value !== 'downloaded') return false
    installState.value = 'installing'
    installError.value = ''
    try {
      const raw = (await requestRpc('update.install', {})) as Record<string, unknown> | null
      const payload = (raw ?? {}) as Record<string, unknown>
      if (payload.ok !== true) throw new Error(String(payload.error || '无法启动安装'))
      installMessage.value = String(payload.message || '已交给系统安装程序')
      // The host says whether this platform's hand-off ends the app. On Windows
      // the installer is already running on its own and needs this process out
      // of the way to replace its files — quitting to the tray is not enough,
      // so the host performs a real exit. If there is no quit bridge (browser)
      // or the exit fails, the app is still here: keep the step retryable
      // instead of showing an install that is waiting for nothing.
      if (payload.quit === true && !(await quitApp())) installState.value = 'downloaded'
      return true
    } catch (err) {
      installState.value = 'downloaded'
      installError.value = err instanceof Error ? err.message : String(err)
      return false
    }
  }

  /** "正在下载 42%（25.6 MB / 61.1 MB）" while a transfer runs. */
  const installProgressLabel = computed(() => {
    if (installState.value !== 'downloading') return ''
    const received = formatMegabytes(installReceived.value)
    const route = installRoute.value === 'accelerator'
      ? ' · EasyNet 加速'
      : installRoute.value === 'proxy'
        ? ' · EasyNet 代理'
        : ''
    if (installTotal.value > 0) {
      const percent = Math.min(100, Math.round((installReceived.value / installTotal.value) * 100))
      return `正在下载 ${percent}%（${received} / ${formatMegabytes(installTotal.value)}）${route}`
    }
    return `正在下载（${received}）${route}`
  })

  /** The installer's size, when the manifest said it, to set expectations. */
  const packageSizeLabel = computed(() => packageSize.value > 0 ? formatMegabytes(packageSize.value) : '')

  /** Human-readable label for whichever source answered the last check. */
  const sourceLabel = computed(() => {
    if (source.value === 'site') return '官网'
    if (source.value === 'github') return 'GitHub Releases'
    return ''
  })

  /** 有新版本、但没有任何可用安装包（本平台）：文案不能说成"已是最新"。 */
  const noInstallerForPlatform = computed(() => reason.value === 'no_installer_for_platform')

  /** 内部测试版：后端跳过远程检查，设置页要说明是跳过而不是"已是最新"。 */
  const internalBuild = computed(() => reason.value === 'internal_build')

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
    internalBuild,
    error,
    installSupported,
    installHint,
    installState,
    installMessage,
    installRoute,
    installError,
    installProgress,
    installReceived,
    installTotal,
    installProgressLabel,
    packageSizeLabel,
    check,
    download,
    downloadInstaller,
    syncFromHost,
    cancelDownload,
    runInstaller,
  }
}

export type CoreUpdateState = ReturnType<typeof useCoreUpdateState>

function formatMegabytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 MB'
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
