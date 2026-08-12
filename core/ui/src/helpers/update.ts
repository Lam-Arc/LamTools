/**
 * Software-update bridge for the "关于与更新" settings section.
 *
 * Version + download routing follow the existing `__LAMTOOLS_*__` window-global
 * pattern: the desktop shell injects the packaged version (from Rust
 * `get_app_info`), and downloads leave the app through the same
 * `__LAMTOOLS_OPEN_URL__` bridge as every other external link.
 *
 * Outside Tauri (plain-browser dev / unit tests) both degrade to safe
 * no-ops, so core/ui never hardcodes the app version.
 */

import { openExternalUrl } from './openUrl'

declare global {
  interface Window {
    __LAMTOOLS_APP_VERSION__?: string
  }
}

/** Version shown when running outside the Tauri shell. */
export const WEB_FALLBACK_VERSION = '0.0.0-dev'

/** The packaged app version, or the web fallback when not in Tauri. */
export function getAppVersion(): string {
  return window.__LAMTOOLS_APP_VERSION__ || WEB_FALLBACK_VERSION
}

/** Open the download URL (installer asset, falling back to the release page) in the system browser. */
export async function openUpdatePage(url: string): Promise<boolean> {
  if (!url) return false
  return openExternalUrl(url)
}
