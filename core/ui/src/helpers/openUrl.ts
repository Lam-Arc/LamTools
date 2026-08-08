/**
 * Open a URL externally — in the OS default browser when running inside the
 * Tauri desktop webview, or a new browser tab otherwise.
 *
 * Why this exists: the Tauri webview has no navigation policy, so a plain
 * `<a href="https://...">` click navigates the app window itself (turning it
 * into a browser). All external links must be routed through here instead.
 *
 * Only http(s) URLs are forwarded; anything else (file:, javascript:, custom
 * schemes) is refused. Relative/in-app links are left for the caller to handle.
 */

declare global {
  interface Window {
    __LAMTOOLS_OPEN_URL__?: (url: string) => Promise<boolean>
  }
}

const EXTERNAL_URL_RE = /^https?:\/\//i

/** True for absolute http(s) URLs that should leave the app. */
export function isExternalUrl(href: string): boolean {
  return EXTERNAL_URL_RE.test(href)
}

/** Open an external http(s) URL in the system browser. No-op for other schemes. */
export async function openExternalUrl(url: string): Promise<boolean> {
  if (!isExternalUrl(url)) return false

  // Tauri desktop: delegate to the Rust `open_external_url` command, which
  // re-validates the scheme and calls the OS opener.
  if (window.__LAMTOOLS_OPEN_URL__) {
    return window.__LAMTOOLS_OPEN_URL__(url)
  }

  // Web / dev: open in a new browser tab. `noopener` avoids leaking the
  // opener reference to the new page.
  try {
    window.open(url, '_blank', 'noopener,noreferrer')
    return true
  } catch {
    return false
  }
}
