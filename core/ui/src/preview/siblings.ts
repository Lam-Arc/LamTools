/**
 * 灯箱左右切换：同一目录里「同一族」的文件序列。
 *
 * user:“灯箱加上切换用的左右键”+(一张图看完就想看下一张：按当前文件所在目录列一层，
 * 只取同类（图片跟图片、视频跟视频…），按名字自然排序，返回当前文件在其中的位置)。
 *
 * 只读一层目录，不做索引；目录读不到就当作“没有可切换的邻居”，箭头不显示，
 * 而不是让按钮点出一个错误。
 */
import type { LamToolsTransport, TransportHttpResponse } from '@/transport'
import { resolvePreviewRoute } from './route'
import { filePreviewTarget, type PreviewFileTarget, type PreviewTarget } from './target'

/** 能左右翻的族：灯箱里点开就能看的那几类（Word/Excel/PPT 只在分屏里看，不参与）。 */
export type PreviewSiblingFamily = 'image' | 'video' | 'audio' | 'pdf' | 'markdown' | 'text'

export interface PreviewSiblings {
  items: PreviewTarget[]
  /** 当前文件在 items 里的下标；-1 表示没对上（例如符号链接改名）。 */
  index: number
}

const EMPTY: PreviewSiblings = { items: [], index: -1 }

function familyOf(path: string): PreviewSiblingFamily | null {
  const route = resolvePreviewRoute(path)
  if (route.kind === 'native') {
    return route.family === 'image' || route.family === 'video' || route.family === 'audio' || route.family === 'pdf'
      ? route.family
      : null
  }
  if (route.kind === 'markdown') return 'markdown'
  if (route.kind === 'text') return 'text'
  return null
}

function directoryOf(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  const cut = normalized.lastIndexOf('/')
  return cut > 0 ? normalized.slice(0, cut) : ''
}

function samePath(left: string, right: string): boolean {
  return left.replace(/\\/g, '/').toLowerCase() === right.replace(/\\/g, '/').toLowerCase()
}

export async function listPreviewSiblings(
  target: PreviewTarget | null | undefined,
  transport: LamToolsTransport | undefined,
): Promise<PreviewSiblings> {
  if (!target || target.kind !== 'file' || !target.path || !transport) return EMPTY
  const file = target as PreviewFileTarget
  const family = familyOf(file.path)
  const directory = directoryOf(file.path)
  if (!family || !directory) return EMPTY

  const query = new URLSearchParams({ path: directory, ...(file.workRoot ? { work_root: file.workRoot } : {}) })
  let response: TransportHttpResponse
  try {
    response = await transport.request<TransportHttpResponse>({
      kind: 'http', method: 'GET', path: `/files/list?${query.toString()}`, timeoutMs: 15_000,
    })
  } catch {
    return EMPTY
  }
  if (!response || response.status < 200 || response.status >= 300) return EMPTY

  let entries: { name?: string; path?: string; directory?: boolean }[] = []
  try {
    const payload = JSON.parse(new TextDecoder().decode(response.body)) as { entries?: typeof entries }
    entries = Array.isArray(payload.entries) ? payload.entries : []
  } catch {
    return EMPTY
  }

  const items = entries
    .filter((entry): entry is { name: string; path: string; directory?: boolean } => (
      Boolean(entry && typeof entry.path === 'string' && entry.name) && !entry.directory
    ))
    .filter(entry => familyOf(entry.path) === family)
    .sort((left, right) => left.name.localeCompare(right.name, 'zh-Hans-CN', { numeric: true }))
    .map(entry => filePreviewTarget(entry.path, {
      ...(file.workRoot ? { workRoot: file.workRoot } : {}),
      ...(file.projectId ? { projectId: file.projectId } : {}),
      ...(file.sessionId ? { sessionId: file.sessionId } : {}),
    }))

  const index = items.findIndex(item => item.kind === 'file' && samePath(item.path, file.path))
  return { items, index }
}
