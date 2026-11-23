import type { CoreSubAgentRun } from '@/types'
import type { CoreSubAgentRef } from './subAgentProjection'

/** 只需要标签的这几项：判断“同一个子代理”与“这块分屏该不该收”。 */
export interface SubAgentTabLike {
  id?: string
  kind: string
  resource?: string
  title?: string
  sessionId?: string
}

/**
 * user:“点击子代理的时候若存在分屏则向分屏添加一个子代理标签页”+
 * (这条标签是不是同一个子代理：会话 id 优先，续跑过的子会话 id 认，名字只做兜底；
 *  主区里的 agent 标签按设计是隐藏的，永远不算“已经打开”。)
 */
export function subAgentTabMatches(
  tab: SubAgentTabLike,
  ref: CoreSubAgentRef,
  run: CoreSubAgentRun | undefined,
  sessionId: string,
): boolean {
  if (tab.kind !== 'agent' || tab.id === 'agent-main') return false
  if (sessionId && tab.sessionId && tab.sessionId !== sessionId) return false
  const resource = String(run?.subSessionId || run?.id || ref.subSessionId || '')
  const title = String(run?.name || ref.name || '').trim().toLowerCase()
  const resourceMatch = resource !== '' && (
    tab.resource === resource
    || tab.resource === run?.id
    || (run?.subSessionIds || []).includes(tab.resource || '')
  )
  const titleMatch = title !== '' && String(tab.title || '').trim().toLowerCase() === title
  return resourceMatch || titleMatch
}

/**
 * user:“若存在分屏则向分屏添加…若不存在分屏，则展开一个分屏并显示”+
 * (优先用户当前所在的辅助屏，其次任意已有的辅助屏；主区不算目标——子代理标签放在那里看不见)。
 */
export function pickSubAgentPane(
  panes: Iterable<string>,
  activePane: string,
  preferred?: string,
): string | null {
  const ids = Array.from(panes).filter(id => id !== 'main')
  if (preferred && ids.includes(preferred)) return preferred
  if (ids.includes(activePane)) return activePane
  return ids[0] ?? null
}
