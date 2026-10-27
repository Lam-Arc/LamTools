import { parseComposerSyntax } from './syntax'

export interface FileReferenceSpan { from: number; to: number; path: string; name: string }
export interface ReferenceSelection { start: number; end: number }

// user:“‘@文件名’实际为一个 绝对地址”+(文档保存完整路径，界面只投影文件名)。
export function fileReference(path: string): string {
  return '@' + JSON.stringify(path.replace(/\\/g, '/'))
}

export function referenceSpans(text: string): FileReferenceSpan[] {
  return parseComposerSyntax(text).flatMap(span => {
    if (span.kind !== 'resource') return []
    let path = span.value
    if (span.raw.startsWith('@"')) {
      try { path = JSON.parse(span.raw.slice(1)) as string } catch { return [] }
    }
    if (!/^(?:[A-Za-z]:[\\/]|\/|pending:\/\/)/.test(path)) return []
    return [{ from: span.start, to: span.end, path, name: path.split(/[\\/]/).pop() || path }]
  })
}

export function insertReferences(text: string, paths: string[], selection: ReferenceSelection | null) {
  const references = paths.map(fileReference).join(' ')
  if (!selection) return { text: references + (text ? '\n' + text : ''), cursor: references.length }
  const from = Math.max(0, Math.min(text.length, selection.start))
  const to = Math.max(from, Math.min(text.length, selection.end))
  const before = text.slice(0, from), after = text.slice(to)
  const insert = (before && !/\s$/.test(before) ? ' ' : '') + references + (after && !/^\s/.test(after) ? ' ' : '')
  return { text: before + insert + after, cursor: before.length + insert.length }
}

export function replaceReference(text: string, fromPath: string, toPath: string) {
  const token = fileReference(fromPath)
  const replaced = text.includes(token)
  return { text: replaced ? text.replace(token, toPath ? fileReference(toPath) : '') : text, replaced }
}

export function activeCompletion(text: string, cursor: number): { trigger: string; query: string; from: number; to: number } | null {
  const before = text.slice(0, cursor)
  let quote = '', code = false, fence = false
  for (let i = 0; i < before.length; i++) {
    if (before.slice(i, i + 3) === '```') { fence = !fence; i += 2; continue }
    if (fence) continue
    if (!quote && before[i] === '`') { code = !code; continue }
    if (code) continue
    if (quote) { if (before[i] === quote && before[i - 1] !== '\\') quote = ''; continue }
    if (before[i] === '"' || before[i] === "'") quote = before[i]!
  }
  if (quote || code || fence) return null
  const match = /(?:^|\s)([/@#])([^\s/@#]*)$/.exec(before)
  return match ? { trigger: match[1]!, query: match[2]!, from: cursor - match[2]!.length - 1, to: cursor } : null
}
