import type { WorkspaceLayout } from './model'

// user:“这里也只需要保留agent/browser”+(根入口只列布局；文件与插件继续通过标签条和抽屉管理)。
export const WORKSPACE_LAYOUTS = { agent: 'Agent', browser: 'Browser' } as const satisfies Record<WorkspaceLayout, string>
