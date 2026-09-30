import type { CorePlanLibraryEntry } from '@lamtools/ui'

/**
 * The plan-library scan, shared by the standalone client's two storage modes.
 *
 * A plan (方案) is one markdown document in the project's 「方案/」 folder:
 * frontmatter (`状态:` / `摘要:`) over the body sections. The title comes from
 * the first `# ` heading, falling back to the file name; an unreadable file
 * degrades to a draft entry rather than hiding from the list — the same rules
 * the desktop's Python scan follows.
 */

export const PLAN_LIBRARY_DIRNAME = '方案'

const STATUS_ALIASES: Record<string, CorePlanLibraryEntry['status']> = {
  '草稿': 'draft',
  draft: 'draft',
  '就绪': 'ready',
  ready: 'ready',
  '执行中': 'executing',
  executing: 'executing',
  '完成': 'done',
  done: 'done',
}

export type PlanLibraryScanEntry = CorePlanLibraryEntry

export function isPlanLibraryPath(path: string): boolean {
  return path === PLAN_LIBRARY_DIRNAME || path.startsWith(`${PLAN_LIBRARY_DIRNAME}/`)
}

export function planPath(name: string): string {
  return `${PLAN_LIBRARY_DIRNAME}/${name}`
}

export function normalizePlanStatus(raw: string | null | undefined): CorePlanLibraryEntry['status'] {
  return STATUS_ALIASES[(raw ?? '').trim().toLowerCase()] ?? 'draft'
}

export function parsePlanFrontmatter(text: string): { status: string | null; summary: string | null } {
  if (!text.startsWith('---')) return { status: null, summary: null }
  const lines = text.split('\n')
  for (let index = 1; index < lines.length; index += 1) {
    if (lines[index].trim() !== '---') continue
    let status: string | null = null
    let summary: string | null = null
    for (const line of lines.slice(1, index)) {
      const separator = line.indexOf(':')
      if (separator <= 0) continue
      const key = line.slice(0, separator).trim().toLowerCase()
      const value = line.slice(separator + 1).trim()
      if (key === '状态' || key === 'status') status = value
      if (key === '摘要' || key === 'summary') summary = value
    }
    return { status, summary }
  }
  return { status: null, summary: null }
}

export function parsePlanDocument(
  text: string,
  name: string,
  updatedAt: number,
  path?: string,
): PlanLibraryScanEntry {
  const { status, summary } = parsePlanFrontmatter(text)
  const body = text.startsWith('---')
    ? text.slice(text.indexOf('\n---', 3) + 1)
    : text
  let title = name.replace(/\.md$/i, '')
  for (const line of body.split('\n')) {
    const heading = line.trim()
    if (heading.startsWith('# ')) {
      title = heading.slice(2).trim()
      break
    }
  }
  return {
    name,
    path: path ?? planPath(name),
    title,
    status: normalizePlanStatus(status),
    summary: summary ?? '',
    size: new TextEncoder().encode(text).length,
    updated_at: Math.floor(updatedAt),
  }
}

export function sortPlanEntries(entries: PlanLibraryScanEntry[]): PlanLibraryScanEntry[] {
  return [...entries].sort((left, right) =>
    right.updated_at - left.updated_at || right.name.localeCompare(left.name),
  )
}
