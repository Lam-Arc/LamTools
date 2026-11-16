/**
 * Resolve a message artifact to the HTTP path its bytes are read from.
 *
 * 这条链路以前只在两种情况下成立：带 `attachment://` 引用，或者带着项目 id 的
 * 相对路径。其余形态（附件库里的绝对存储路径、没有项目上下文时的相对路径、
 * 被换成引用的旧条目）一律解析成空串，界面只能显示"图片暂时取不到"——用户看到的
 * 就是"多媒体图片全部加载失败"。
 *
 * 这里按可靠性从高到低给出候选，最后一条兜底 `/files/read-reference` 是文件引用
 * 预览一直在用的通道，它对绝对路径与工作区相对路径都成立，所以只要条目上还有
 * 任何一个路径字段，就不会再解析失败。
 */

export interface ArtifactSourceInput {
  uri?: string
  path?: string
  artifact_id?: string
  metadata?: Record<string, unknown>
}

export interface ArtifactSourceContext {
  projectId?: string | null
  workRoot?: string | null
}

function rawPath(artifact: ArtifactSourceInput): string {
  if (typeof artifact.uri === 'string' && artifact.uri.trim()) return artifact.uri.trim()
  if (typeof artifact.path === 'string' && artifact.path.trim()) return artifact.path.trim()
  const fromMetadata = artifact.metadata?.path
  return typeof fromMetadata === 'string' ? fromMetadata.trim() : ''
}

function stripWorkspaceScheme(path: string): string {
  return path.startsWith('workspace://') ? path.slice('workspace://'.length) : path
}

function referenceQuery(path: string, workRoot?: string | null): string {
  const params = new URLSearchParams({ path })
  if (workRoot) params.set('work_root', workRoot)
  return params.toString()
}

export function artifactSourcePath(
  artifact: ArtifactSourceInput | null | undefined,
  context: ArtifactSourceContext = {},
): string {
  if (!artifact) return ''
  const projectId = context.projectId ? String(context.projectId) : ''
  const workRoot = context.workRoot ? String(context.workRoot) : ''
  const path = rawPath(artifact)

  // 1) 附件引用：附件系统的下载口，桌面端最稳的一条。
  if (path.startsWith('attachment://')) {
    const id = path.slice('attachment://'.length).trim()
    return id ? `/attachments/${encodeURIComponent(id)}/download` : ''
  }
  // 2) 附件库的绝对存储路径：一级目录是**内容 sha256**，不是附件 id
  //    （实测 `attachments/<sha256>/<文件名>`，目录名与文件哈希完全一致）。
  //    换成 `/attachments/<sha>/download` 只会 404，所以这类路径不在这里改写，
  //    交给末位的文件引用通道按绝对路径读——那才是真能取到字节的一条。
  // 3) 登记过的产物：按 id 取当前版本，后端自己定位磁盘落点，不依赖 path 是否正确。
  if (projectId && artifact.artifact_id) {
    return `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/file`
  }
  const relative = stripWorkspaceScheme(path)
  // 盘符绝对路径不是"工作区相对路径"，走项目文件接口只会 404（它只认工作区内路径），
  // 所以这类一律跳过第 4 步，直接交给文件引用通道。
  const driveAbsolute = /^[a-zA-Z]:[\\/]/.test(relative)
  // 4) 工作区相对路径：项目文件接口。
  if (projectId && relative && !driveAbsolute) {
    return `/projects/${encodeURIComponent(projectId)}/files/raw?path=${encodeURIComponent(relative)}`
  }
  // 5) 兜底：文件引用通道，绝对路径与相对路径都成立，存在性由后端校验。
  if (relative) {
    return `/files/read-reference?${referenceQuery(relative, workRoot)}`
  }
  return ''
}
