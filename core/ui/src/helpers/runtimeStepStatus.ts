import { t } from '@/i18n/index.ts'
import type { CoreRuntimeStepStatus } from '@/types.ts'

// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(计划卡与侧栏共用步骤状态文字并跟随界面语言)。
const labels: Record<CoreRuntimeStepStatus, string> = {
  pending: '待处理', running: '运行中', completed: '已完成', failed: '失败', skipped: '已跳过',
}
export function runtimeStepStatusLabel(status: CoreRuntimeStepStatus): string {
  return t(labels[status] ?? String(status))
}
