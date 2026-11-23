/**
 * 工作区类型（V2-C2）。
 *
 * user:“新建 core/ui/src/workspace/types.ts，把 SplitTab/SplitContent/SurfaceMode 等
 * 仍在用的类型搬过去（字段保持兼容），全仓改 import”+
 * (这些类型原来长在已下线的旧布局与形态模块里，和旧算法绑在一起；
 *  V2 之后布局算法只在新引擎里，内容层需要的只是“一份内容长什么样、被摆在哪”。
 *  字段保持兼容，所以改 import 不需要改任何调用点。)
 */
import type { AuxiliaryContext } from '@/auxiliary/workspace'

export type { AuxiliaryContext }

/** 内容类型：工作区只管“这格装什么”，不再区分 page/editor/files 的摆放差异。 */
export type SplitContent = 'page' | 'browser' | 'editor' | 'preview' | 'files' | 'agent' | 'conversation' | 'plugin'

/** 三种呈现：分屏 / 聚焦 / 浮层（灯箱不进工作区模型）。 */
export type SurfaceMode = 'split' | 'focus' | 'float'

/** 浮窗外框矩形（DOM 画边框、圆角、阴影用的那个框）。 */
export interface SurfaceFrame { x: number; y: number; width: number; height: number }

/**
 * 一份内容实例。
 *
 * user:“内容实例与布局分离：同一 tab 对象在移动间不复制（不要 {...tab}）”+
 * (所以这里是**实例**描述，不是位置描述：位置在 WorkspaceModel 里。
 *  `surface/surfaceFrame/surfaceExpanded` 保留为兼容字段——旧存档与世界仍在读它们，
 *  V2 形态迁移完成后可再移除。)
 */
export interface SplitTab {
  id: string
  kind: SplitContent
  title: string
  resource: string
  sessionId?: string
  root?: string
  projectId?: string
  context?: AuxiliaryContext
  modelId?: string
  contextSent?: boolean
  profile?: string
  surface?: SurfaceMode
  surfaceExpanded?: boolean
  surfaceFrame?: SurfaceFrame
  zoom?: number
  /** user:“由 agent 开的标签页打一个 tag：agent”+(运行时标记：角标、收尾策略、所有权读它；
   *  Rust 标签不跨重启，所以不写进存档)。 */
  tag?: 'agent'
  paneHint?: string
}

/**
 * 工作区控制器的类型名。
 *
 * user:“auxiliary/workspace.ts（控制器类型）、CoreContentRoot.vue…按新控制器改”+
 * (旧代码到处 import `WorkspaceController`；这里给一个稳定的类型名，
 *  让依赖方不必知道具体实现文件在哪。)
 */
export type { WorkspaceController } from './useWorkspace'

/**
 * 尺寸常量从 `constants.ts` 再导出：旧测试与内容组件仍从 `workspace/types` 取标签栏高度。
 * user:“迁移时丢一个常量就会让 contentRect 算成 NaN”+(保留一个稳定入口，避免再散落)。
 */
export { SPLIT_TAB_BAR_HEIGHT, WORKSPACE_HEADER_HEIGHT } from './constants'
