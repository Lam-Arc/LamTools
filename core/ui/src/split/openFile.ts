import { baseName, splitContentFor } from './preview'
import { splitPreviewEnabled } from './previewPreference'
import type { SplitWorkspaceController } from './useSplitWorkspace'
import type { LamToolsTransport, TransportHttpResponse } from '@/transport'

export interface SplitOpenScope {
  workRoot?: string
  projectId?: string
  sessionId?: string
  /** 从哪块屏旁边新开；只在没有同类标签可复用时使用。 */
  fromPane?: string
  /** 用户主动选的“在分屏中打开”：默认打开开关关闭时也照做。 */
  force?: boolean
}

/**
 * user:“默认打开也跟文本文件一样 用分屏预览打开”+
 * (文件打开只有一个入口：文本进编辑器，其余进预览器；已有同类标签就复用那块屏)。
 * user:“设置中把它标记为实验性功能”+(关掉实验性开关后预览类文件不在这里接管，交回调用方)。
 */
export function openFileInSplit(controller: SplitWorkspaceController, path: string, scope: SplitOpenScope = {}) {
  const kind = splitContentFor(path)
  if (!scope.force && kind === 'preview' && !splitPreviewEnabled()) return null
  const sameKind = controller.tabs.value.find(({ tab }) => tab.kind === kind)?.pane
  const from = scope.fromPane
  const pane = sameKind || (from ? controller.split(from, 'right') || from : undefined)
  return controller.add(
    kind,
    path,
    baseName(path),
    pane,
    scope.sessionId,
    scope.workRoot,
    scope.projectId,
  )
}

/** 预览开关关闭或分屏不可用时，文件回到稳定的“默认应用打开”通道。 */
export async function openFileWithDefaultApp(transport: LamToolsTransport | undefined, path: string, workRoot = ''): Promise<boolean> {
  if (!transport || !path) return false
  try {
    const response = await transport.request<TransportHttpResponse>({
      kind: 'http', method: 'POST', path: '/files/open-reference',
      headers: { 'Content-Type': 'application/json' },
      body: new TextEncoder().encode(JSON.stringify({ path, ...(workRoot ? { work_root: workRoot } : {}) })),
    })
    return response.status >= 200 && response.status < 300
  } catch { return false }
}
