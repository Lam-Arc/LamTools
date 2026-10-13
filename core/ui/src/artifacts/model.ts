/**
 * 成果库的纯值层：规范化、角色/类型/状态推导、标签与图标。
 *
 * 右栏的成果库面板与资料库的「资料」分区共用这一份——同一种数据只能有一套
 * 判断，否则"文件缺失"在两个界面上会各说各话。这里不碰 DOM、不碰响应式，
 * 只做值的换算，方便两处复用与单独测试。
 */
import {
  File,
  FileCode2,
  FileSpreadsheet,
  FileText,
  Film,
  Image as ImageIcon,
  Music,
  Package,
  Presentation,
  type LucideIcon,
} from 'lucide-vue-next'
import type { ArtifactRole, ProjectArtifact } from '../types'

export const ROLE_VALUES: ArtifactRole[] = ['input', 'intermediate', 'deliverable']

export const KIND_ICONS: Record<string, LucideIcon> = {
  image: ImageIcon,
  video: Film,
  audio: Music,
  pdf: FileText,
  document: File,
  code: FileCode2,
  spreadsheet: FileSpreadsheet,
  presentation: Presentation,
  file: Package,
  file_change: FileText,
}

const EXTENSION_KINDS: Array<[string[], string]> = [
  [['xlsx', 'xls', 'ods', 'csv', 'tsv'], 'spreadsheet'],
  [['pptx', 'ppt', 'odp'], 'presentation'],
  [['pdf'], 'pdf'],
  [['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'heic'], 'image'],
  [['mp4', 'webm', 'mov', 'mkv', 'avi', 'm4v'], 'video'],
  [['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac'], 'audio'],
  [['md', 'markdown', 'txt', 'log', 'rtf', 'doc', 'docx', 'odt'], 'document'],
  [[
    'ts', 'tsx', 'js', 'jsx', 'vue', 'py', 'rs', 'go', 'java', 'c', 'cpp', 'h', 'hpp', 'cs',
    'rb', 'php', 'sh', 'ps1', 'sql', 'html', 'css', 'scss', 'json', 'jsonc', 'yaml', 'yml', 'toml', 'xml',
  ], 'code'],
]

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

export function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

export function roleFor(raw: Record<string, unknown>): ArtifactRole {
  const explicit = stringValue(raw.role || asRecord(raw.metadata)?.role)
  if (ROLE_VALUES.includes(explicit as ArtifactRole)) return explicit as ArtifactRole
  const source = stringValue(raw.source || asRecord(raw.metadata)?.source).toLowerCase()
  if (source === 'user_upload' || source === 'user' || source === 'input') return 'input'
  if (source === 'agent_generated' || source === 'agent' || source === 'generated') return 'deliverable'
  if (stringValue(raw.kind) === 'file_change') return 'deliverable'
  return '' as ArtifactRole
}

/**
 * One raw artifact payload → the shape both surfaces render.
 *
 * 成果没有历史版本：内容就是路径上的当前文件，后端说 missing 就是文件不在了，
 * 绝不让它看起来像能打开。
 */
export function normalizeArtifact(value: unknown): ProjectArtifact | null {
  const raw = asRecord(value)
  if (!raw) return null
  const metadata = asRecord(raw.metadata) || {}
  const artifactId = stringValue(raw.artifact_id || raw.id)
  if (!artifactId) return null
  const path = stringValue(raw.path || raw.uri || metadata.path)
  const deleted = raw.deleted === true
  const availability = stringValue(raw.availability || metadata.availability).toLowerCase()
  const missing = raw.missing === true || availability === 'missing' || availability === 'metadata_only'
  const role = roleFor(raw)
  if (!ROLE_VALUES.includes(role as ArtifactRole)) return null
  return {
    ...raw,
    artifact_id: artifactId,
    name: stringValue(raw.name || metadata.name || path.split(/[\\/]/).pop() || artifactId),
    kind: stringValue(raw.kind || metadata.kind || 'file'),
    mime_type: stringValue(raw.mime_type || metadata.mime_type),
    path,
    uri: stringValue(raw.uri),
    role,
    status: stringValue(raw.status || metadata.status) || undefined,
    source: stringValue(raw.source || metadata.source),
    provenance: raw.provenance ?? metadata.provenance,
    availability: availability || undefined,
    created_at: stringValue(raw.created_at || metadata.created_at),
    updated_at: stringValue(raw.updated_at || metadata.updated_at),
    thread_id: stringValue(raw.thread_id || metadata.thread_id),
    turn_id: stringValue(raw.turn_id || metadata.turn_id),
    item_id: stringValue(raw.item_id || metadata.item_id),
    missing,
    deleted,
    // 资料库新增的两个用户状态；老记录没有就是未收藏、未归档。
    favorite: raw.favorite === true,
    folder: stringValue(raw.folder),
  }
}

export function extractArtifactRows(result: Record<string, unknown>): unknown[] {
  if (Array.isArray(result.artifacts)) return result.artifacts
  if (Array.isArray(result.items)) return result.items
  const data = asRecord(result.data)
  if (data && Array.isArray(data.artifacts)) return data.artifacts
  return []
}

/** A last-moment kind refinement so an `.xlsx` labelled `file` still reads as a spreadsheet. */
export function inferredKind(kind: string, name = ''): string {
  if (!['file', 'document', 'file_change'].includes(kind)) return kind
  const ext = name.split('.').pop()?.toLowerCase() || ''
  for (const [extensions, resolved] of EXTENSION_KINDS) {
    if (extensions.includes(ext)) return resolved
  }
  return kind
}

export function kindIcon(kind: string, name = ''): LucideIcon {
  return KIND_ICONS[inferredKind(kind, name)] || File
}

export function kindLabel(kind: string, name = ''): string {
  const resolved = inferredKind(kind, name)
  const labels: Record<string, string> = {
    image: '图片', video: '视频', audio: '音频', pdf: 'PDF', document: '文档', code: '代码',
    spreadsheet: '表格', presentation: '演示文稿', file: '文件', file_change: '文件改动',
  }
  return labels[resolved] || resolved || '文件'
}

export function roleLabel(role?: string): string {
  return ({ input: '用户', intermediate: '中间产物', deliverable: '产物' } as Record<string, string>)[role || ''] || '成果'
}

export function artifactStatus(item: ProjectArtifact): string {
  if (item.deleted) return 'deleted'
  if (item.missing) return 'missing'
  const value = stringValue(item.status).toLowerCase()
  if (value === 'in_progress') return 'running'
  return value || 'ready'
}

export function statusLabel(item: ProjectArtifact): string {
  const labels: Record<string, string> = {
    ready: '就绪', running: '处理中', completed: '已完成', failed: '失败', missing: '文件缺失', deleted: '已移除',
  }
  return labels[artifactStatus(item)] || artifactStatus(item)
}

export function provenanceLabel(item: ProjectArtifact): string {
  const provenance = asRecord(item.provenance)
  if (provenance) {
    const label = stringValue(provenance.label || provenance.name || provenance.source)
    if (label) return label
  }
  if (item.source === 'user_upload' || item.source === 'user') return '用户上传'
  if (item.source === 'agent_generated' || item.source === 'agent') return 'Agent 生成'
  return item.source || '工作区'
}

/** 一次工作台事件是否与成果有关——决定列表要不要悄悄刷新。 */
export function isArtifactSignal(signal: unknown): boolean {
  const record = asRecord(signal)
  if (!record) return false
  const haystack = [record.method, record.event_type, record.type].map(stringValue).join(' ')
  if (haystack.includes('artifact')) return true
  const payload = asRecord(record.payload)
  if (!payload) return false
  if (payload.artifact_id || payload.artifactId) return true
  if (Array.isArray(payload.artifacts) && payload.artifacts.length) return true
  return payload.kind === 'artifact.changed'
}

/** 一个成果所在的归档层（'' = 未归档）。 */
export function folderOf(item: ProjectArtifact): string {
  return (item.folder || '').replace(/^\/+|\/+$/g, '')
}

export function folderParent(path: string): string {
  return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
}

export function folderName(path: string): string {
  return path.split('/').pop() || path
}

/** 资料库类型页签的分组：把 kind 归到界面上那几格。 */
export function mediaGroup(item: ProjectArtifact): 'image' | 'document' | 'spreadsheet' | 'media' | 'other' {
  const kind = inferredKind(item.kind, item.name)
  if (kind === 'image') return 'image'
  if (kind === 'spreadsheet' || kind === 'presentation') return 'spreadsheet'
  if (kind === 'video' || kind === 'audio') return 'media'
  if (kind === 'document' || kind === 'pdf' || kind === 'code' || kind === 'file' || kind === 'file_change') return 'document'
  return 'other'
}


/** 成果内容的取字节地址：永远读当前那一份（工作区文件或上传原件）。 */
export function artifactHttpPath(projectId: string, artifact: ProjectArtifact): string {
  const reference = artifact.path || artifact.uri || ''
  if (artifact.artifact_id) {
    const query = new URLSearchParams()
    if (reference) query.set('path', reference)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/file${suffix}`
  }
  if (reference.startsWith('attachment://')) {
    return `/attachments/${encodeURIComponent(reference.slice('attachment://'.length))}/download`
  }
  if (reference.startsWith('workspace://')) {
    return `/projects/${encodeURIComponent(projectId)}/files/raw?path=${encodeURIComponent(reference.slice('workspace://'.length))}`
  }
  return reference
    ? `/projects/${encodeURIComponent(projectId)}/files/raw?path=${encodeURIComponent(reference)}`
    : ''
}

/** 有没有可以直接当缩略图渲染的字节（图片且实体存在）。 */
export function isThumbnailable(item: ProjectArtifact): boolean {
  if (item.missing || item.deleted) return false
  const mime = (item.mime_type || '').toLowerCase()
  if (mime.startsWith('image/') && !mime.includes('svg')) return true
  return inferredKind(item.kind, item.name) === 'image'
}

/**
 * 视频：字节不能直接当缩略图，要先解出首帧再画成图，所以它和图片分开判断，
 * 也不占 `isThumbnailable` 这个名字（那个名字说的是"字节即图"）。
 */
export function isVideoArtifact(item: ProjectArtifact): boolean {
  if (item.missing || item.deleted) return false
  const mime = (item.mime_type || '').toLowerCase()
  if (mime.startsWith('video/')) return true
  return inferredKind(item.kind, item.name) === 'video'
}

/** 文件名的扩展名（大写，最多 5 位；再长就不是能塞进徽标的信息了）。 */
export function fileExtension(name: string): string {
  const match = /\.([A-Za-z0-9]{1,5})$/.exec(name || '')
  return match ? match[1].toUpperCase() : ''
}

export type MaterialCoverStyle = 'page' | 'media'

/**
 * 没有真实预览时自绘封面的画法：文档类画一页纸（下缘一条类型色带），
 * 音视频与图片类画一枚圆底图标。两者共用同一份 kind 推导，不另立判断。
 */
export function coverStyle(kind: string, name = ''): MaterialCoverStyle {
  const resolved = inferredKind(kind, name)
  return resolved === 'image' || resolved === 'video' || resolved === 'audio' ? 'media' : 'page'
}

/**
 * 成果引用在磁盘上的绝对路径：workspace:// 相对项目根展开成真实位置，
 * 其余引用（attachment:// 等）没有磁盘落点，原样返回。路径展示与复制都用它，
 * 不再让人看到内部协议前缀。
 */
export function absoluteArtifactPath(item: Pick<ProjectArtifact, 'path' | 'uri'>, workRoot?: string | null): string {
  const reference = item.path || item.uri || ''
  if (!reference.startsWith('workspace://')) return reference
  if (!workRoot) return reference
  const root = workRoot.replace(/[\\/]+$/, '')
  const relative = reference.slice('workspace://'.length)
  if (/^[A-Za-z]:/.test(root)) return `${root}\\${relative.replace(/\//g, '\\')}`
  return `${root}/${relative}`
}

// ---------------------------------------------------------------------------
// 消息流「本轮产出」的入选判定（2026-10-12 用户规则）
//
// 一个回合写过的文件不再全部进产物区：只有①本回合被收进资料库的文件、②本回合
// 汇报文本里以相对或绝对路径出现过的文件才进。这两个判定是纯值换算，放在这里
// 与资料库共用同一份规范化，避免界面上"同一个文件"有两种写法。
// ---------------------------------------------------------------------------

/** 消息流产物区的入选输入。 */
export interface TurnArtifactSelectionOptions {
  /** 本回合的汇报文本（最终答复）：文件据此被认领。 */
  reportText: string
  /** 本回合经资料库工具登记的文件（工作区相对路径，已规范化的集合）。 */
  libraryPaths: ReadonlySet<string>
  /** 工作根：把相对路径展开成绝对路径再匹配一次；缺省时只匹配相对写法。 */
  workRoot?: string | null
}

const WORKSPACE_REFERENCE_PREFIX = 'workspace://'

/** 路径引用的规范形：workspace:// 前缀剥掉、反斜杠归一、去掉 ./ 与重复斜杠。 */
export function normalizeArtifactReference(raw: unknown): string {
  let value = String(raw ?? '').trim().replace(/\\/g, '/')
  if (value.startsWith(WORKSPACE_REFERENCE_PREFIX)) value = value.slice(WORKSPACE_REFERENCE_PREFIX.length)
  while (value.startsWith('./')) value = value.slice(2)
  return value.replace(/\/{2,}/g, '/')
}
/** 绝对引用（盘符或根路径）——它不在工作区相对命名空间里。 */
export function isAbsoluteArtifactReference(value: string): boolean {
  return /^[A-Za-z]:\//.test(value) || value.startsWith('/')
}

/** 入选判定用的那一个路径引用：path 优先，其次 metadata.path，最后 uri。 */
export function artifactListingReference(artifact: Pick<ProjectArtifact, 'path' | 'uri'> & { metadata?: Record<string, unknown> }): string {
  const metadataPath = typeof artifact.metadata?.path === 'string' ? artifact.metadata.path : ''
  return normalizeArtifactReference(artifact.path || metadataPath || artifact.uri || '')
}

/**
 * 汇报文本有没有以相对或绝对路径提到这个文件。
 * 兼容正反斜杠两种分隔符，以及工作根展开后的绝对写法（Windows 盘符不区分大小写）。
 */
export function reportMentionsArtifactPath(
  reportText: string,
  reference: string,
  workRoot?: string | null,
): boolean {
  const text = String(reportText || '').replace(/\\/g, '/')
  const normalized = normalizeArtifactReference(reference)
  if (!text || !normalized) return false
  if (text.includes(normalized)) return true
  if (isAbsoluteArtifactReference(normalized)) return false
  const root = String(workRoot || '').replace(/\\/g, '/').replace(/\/+$/, '')
  if (!root) return false
  const absolute = `${root}/${normalized}`
  if (text.includes(absolute)) return true
  return /^[A-Za-z]:\//.test(absolute) && text.toLowerCase().includes(absolute.toLowerCase())
}

/**
 * 这个产物条目要不要进「本轮产出」区。
 * - 生成图片（kind=image）不套两条规则：它们本就是这个区的另一类内容，不是
 *   "本回合写过的文件"，写法也不总是工作区路径（可能是内联 data URL）。
 * - 其余条目要在本回合的入库清单里，或被汇报文本以路径提到，才留下。
 */
export function shouldListTurnArtifact(
  artifact: Pick<ProjectArtifact, 'kind' | 'path' | 'uri'> & { metadata?: Record<string, unknown> },
  options: TurnArtifactSelectionOptions,
): boolean {
  if (String(artifact.kind || '') === 'image') return true
  const reference = artifactListingReference(artifact)
  if (!reference) return false
  if (!isAbsoluteArtifactReference(reference) && options.libraryPaths.has(reference)) return true
  return reportMentionsArtifactPath(options.reportText, reference, options.workRoot)
}

/**
 * 汇报文本里出现的文件路径候选（2026-10-12 用户口径：汇报里点到的文件也算产物）。
 * 反引号包裹、Markdown 链接、裸路径都收；只收"像路径"的：带目录（或盘符）且有扩展名。
 * 反斜杠与正斜杠两种写法都认（统一成 /）。
 */
export function artifactPathsInText(text: string): string[] {
  const normalized = String(text || '').replace(/\\/g, '/')
  const found: string[] = []
  const push = (raw: string): void => {
    // 链接写法 `[文字](路径)`：从 '](' 之后取路径本体。
    const link = raw.lastIndexOf('](')
    const value = (link >= 0 ? raw.slice(link + 2) : raw)
      .replace(/^[`'“"（(\[【]+/, '')
      .replace(/[`'“"，。；;：:）)\]】>]+$/, '')
      .replace(/^[^A-Za-z0-9._/\-]+/, '')
      .trim()
    if (!value) return
    if (!value.includes('/')) return
    const tail = value.split('/').pop() || ''
    if (!/\.[A-Za-z0-9]{1,8}$/.test(tail)) return
    if (!found.includes(value)) found.push(value)
  }
  // 绝对写法自带起点；相对写法要求前面是边界（空白/引号/反引号/括号），
  // 免得把中文句子和链接文字一起吞进来。
  for (const match of normalized.matchAll(/([A-Za-z]:\/[^\s`"'<>|]*)|(?:^|[\s`"'“”（(【<\[])((?:[^\s`"'<>|]+\/)+[^\s`"'<>|]*)/g)) {
    push(match[1] ?? match[2] ?? '')
  }
  return found
}

/**
 * 把汇报里的路径候选落到工作区相对引用：相对写法原样，盘符绝对写法按工作根归一
 * （盘符不区分大小写），越出工作区或没有工作根时返回 ''——那种文件不是项目产物。
 */
export function workspaceRelativeFromReportPath(value: string, workRoot?: string | null): string {
  const reference = normalizeArtifactReference(value)
  if (!reference) return ''
  if (!isAbsoluteArtifactReference(reference)) return reference.replace(/^\/+/, '')
  const root = normalizeArtifactReference(workRoot || '').replace(/\/+$/, '')
  if (!root) return ''
  const lowered = reference.toLowerCase()
  const loweredRoot = root.toLowerCase()
  if (lowered === loweredRoot) return ''
  return lowered.startsWith(`${loweredRoot}/`) ? reference.slice(root.length + 1) : ''
}
