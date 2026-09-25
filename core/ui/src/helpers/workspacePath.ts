/**
 * Workspace-relative path handling for artifact/file previews.
 *
 * The desktop shell renders workspace files through the Tauri asset protocol,
 * which needs an absolute path built from the work root. A message part's
 * `uri` is data owned by a model/tool result, so it must not be able to name a
 * path outside that root: `..` segments, absolute paths and Windows drives are
 * refused here (2026-09-25 audit P2 — the join used to trust the string as-is,
 * leaving only the shell's asset scope as a backstop).
 */

/** Normalize a workspace-relative path, or return '' when it may escape the root. */
export function workspaceRelativePath(raw: unknown): string {
  if (typeof raw !== 'string') return ''
  const unified = raw.trim().replace(/\\/g, '/')
  if (!unified) return ''
  if (/^[a-zA-Z]:/.test(unified)) return '' // drive-absolute (C:/…)
  const segments: string[] = []
  for (const segment of unified.split('/')) {
    if (!segment || segment === '.') continue
    if (segment === '..') return ''
    segments.push(segment)
  }
  return segments.join('/')
}
