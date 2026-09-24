import type { LocalRepository } from '../storage'
import {
  hasEmbeddedRustCore,
  listEmbeddedProjectFiles,
  readEmbeddedProjectFile,
} from '../native/rustAgent'

/** Search the device-owned project files, including files written by native tools. */
export async function searchStandaloneWorkspace(
  repository: LocalRepository,
  params: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const query = String(params.query || '').trim()
  if (!query) throw new Error('query 不能为空')
  const mode = String(params.mode || 'content')
  if (mode !== 'files' && mode !== 'content') throw new Error(`mode 无效: ${mode}`)
  const limit = Math.max(1, Math.min(100, Number(params.limit) || 20))
  const results: Array<{ path: string; line?: number; content?: string }> = []
  const projects = await repository.listProjects()
  for (const project of projects) {
    const nativeFiles = hasEmbeddedRustCore() ? await collectNativeFiles(project.id) : []
    const legacyFiles = await repository.listProjectFiles(project.id)
    const nativeSizes = new Map(nativeFiles.map(file => [file.path, file.size]))
    const paths = new Set([...nativeSizes.keys(), ...legacyFiles.map(file => file.path)])
    for (const path of [...paths].sort()) {
      if (results.length >= limit) break
      const displayPath = projects.length > 1 ? `${project.name}/${path}` : path
      if (mode === 'files') {
        if (path.split('/').at(-1)?.toLowerCase().includes(query.toLowerCase())) results.push({ path: displayPath })
        continue
      }
      if ((nativeSizes.get(path) || 0) > 2_000_000) continue
      let nativeFile: Awaited<ReturnType<typeof readEmbeddedProjectFile>> = null
      if (hasEmbeddedRustCore()) {
        try { nativeFile = await readEmbeddedProjectFile(project.id, path) }
        catch { continue } // Binary or unreadable file: continue searching text files.
      }
      const content = nativeFile?.content ?? legacyFiles.find(file => file.path === path)?.content
      if (typeof content !== 'string') continue
      for (const [index, line] of content.split(/\r?\n/).entries()) {
        if (!line.includes(query)) continue
        results.push({ path: displayPath, line: index + 1, content: line.trim().slice(0, 200) })
        if (results.length >= limit) break
      }
    }
    if (results.length >= limit) break
  }
  return { mode, query, results, total: results.length, truncated: results.length >= limit }
}

async function collectNativeFiles(projectId: string): Promise<Array<{ path: string; size: number }>> {
  const files: Array<{ path: string; size: number }> = []
  const pending = ['']
  while (pending.length) {
    const directory = pending.pop()!
    for (const entry of await listEmbeddedProjectFiles(projectId, directory)) {
      const path = directory ? `${directory}/${entry.name}` : entry.name
      if (entry.type === 'directory') pending.push(path)
      else files.push({ path, size: entry.size })
    }
  }
  return files
}
