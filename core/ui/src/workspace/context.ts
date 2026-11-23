/**
 * 工作区注入口（V2-C2）。
 *
 * user:“auxiliary/workspace.ts、CoreContentRoot.vue…按新控制器改；没有存在意义的旧入口直接删”+
 * (旧的注入键长在已下线的旧内核里，随它一起下线；
 *  这里提供同义的注入键，内容组件靠它拿控制器，不需要知道控制器在哪儿创建。)
 */
import { hasInjectionContext, inject, type InjectionKey } from 'vue'
import type { WorkspaceController } from './types'

export const WorkspaceKey: InjectionKey<WorkspaceController> = Symbol('workspace')

export function useOptionalWorkspace(): WorkspaceController | null {
  return hasInjectionContext() ? inject(WorkspaceKey, null) : null
}
