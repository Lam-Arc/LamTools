export function statusLabel(status: string): string {
  if (!status || status === 'undefined' || status === 'null') return '未知'
  const map: Record<string, string> = {
    active: '可用',
    idle: '空闲',
    running: '运行中',
    completed: '已完成',
    done: '已完成',
    failed: '失败',
    error: '错误',
    waiting: '等待',
    pending: '等待中',
    skipped: '已跳过',
    in_progress: '进行中',
  }
  return map[status] || status
}

export function phaseLabel(phase: string): string {
  if (!phase || phase === 'undefined' || phase === 'null') return '暂无任务'
  const map: Record<string, string> = {
    idle: '空闲',
    planning: '规划',
    executing: '执行',
    verifying: '验证',
    reviewing: '审核',
    completed: '已完成',
    done: '完成',
    failed: '失败',
    error: '错误',
    waiting_for_user: '等待用户',
  }
  return map[phase] || phase
}

export function stepKindLabel(stepType: string, toolName?: string | null): string {
  if (toolName) return toolName
  const map: Record<string, string> = {
    tool: '工具调用',
    action: '执行动作',
    agent_progress: 'Agent 进度',
    agent_call: 'Agent 调用',
    llm: '模型调用',
    message: '消息',
  }
  return map[stepType] || stepType
}

export function runtimeTextLabel(text: string): string {
  if (!text || text === 'undefined' || text === 'null') return '暂无任务'
  if (text === 'Complete') return '已完成'
  if (text === 'Cancelled') return '已取消'
  if (text === 'Resumed') return '已恢复'
  if (text === 'Failed') return '失败'
  if (text === 'Error') return '错误'
  if (text === 'Starting...') return '启动中'
  if (text === 'Receiving...') return '接收回复'
  if (text.startsWith('Error:')) return text.replace('Error:', '错误：')
  if (text.startsWith('Step:')) return '正在执行步骤'
  if (text.startsWith('Phase:')) return text.replace('Phase:', '阶段：')
  if (text.startsWith('Progress:')) return text.replace('Progress:', '进度：')
  if (text.startsWith('Git:')) {
    const gitType = text.replace('Git:', '').trim()
    return gitType && gitType !== 'undefined' ? `Git：${gitType}` : '暂无 Git 状态'
  }
  return text
}

export function formatTime(iso: string): string {
  if (!iso || iso === 'undefined' || iso === 'null') return '刚刚'
  try {
    const time = new Date(iso).getTime()
    if (Number.isNaN(time)) return '刚刚'
    const diffMin = Math.floor((Date.now() - time) / 60000)
    if (diffMin < 1) return '刚刚'
    if (diffMin < 60) return `${diffMin} 分钟前`
    const diffH = Math.floor(diffMin / 60)
    return diffH < 24 ? `${diffH} 小时前` : new Date(iso).toLocaleDateString()
  } catch {
    return '刚刚'
  }
}

export function shortSha(sha: string): string {
  return sha ? sha.slice(0, 7) : ''
}

export function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value)
}

export function normalizeMessageText(value: unknown): string {
  return stringValue(value)
    .replace(/[\s。.,，、；;]+/g, '')
    .trim()
}

export function numberValue(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export function businessText(value: string): string {
  const text = String(value || '').trim()
  if (!text || text === 'undefined' || text === 'null') return ''
  const lower = text.toLowerCase()
  if (lower.startsWith('let me')) return ''
  if (lower.startsWith('calling ')) return ''
  if (lower.startsWith('call tool:')) return ''
  if (/^\{['"]?[a-z_]+['"]?\s*:/.test(text) || /^\[[\s{]/.test(text)) return ''
  if (lower.startsWith('plan ready')) return '计划已生成，确认后继续执行。'
  if (lower.startsWith('review and confirm')) return '请确认后继续。'
  if (lower === 'ok' || lower === 'done') return lower === 'ok' ? '成功' : '已完成'
  return localizeStatusWords(text)
}

export function isTechnicalNoise(value: string): boolean {
  const text = String(value || '').trim()
  if (!text) return true
  const lower = text.toLowerCase()
  return lower === '成功'
    || lower === '已完成'
    || lower.startsWith('call tool:')
    || lower.startsWith('calling ')
    || /^\{['"]?[a-z_]+['"]?\s*:/.test(text)
    || /^\[[\s{]/.test(text)
}

export function technicalReasonLabel(value: string): string {
  const text = String(value || '').trim()
  if (!text || text === 'undefined' || text === 'null') return ''
  const clean = text.toLowerCase()
  const map: Record<string, string> = {
    completion_verification_failed: '完成验证失败',
    validation_failed: '验证失败',
    permission_denied: '权限不足',
    llm_error: '模型调用失败',
    max_retries_exceeded: '多次重试后仍失败',
  }
  if (map[clean]) return map[clean]
  if (clean.includes('completion') && clean.includes('verification') && clean.includes('failed')) return '完成验证失败'
  if (clean.includes('permission') && clean.includes('denied')) return '权限不足'
  if (clean.includes('retry')) return '多次重试后仍失败'
  if (clean.includes('failed')) return '执行失败'
  if (clean.includes('error')) return '运行出错'
  return businessText(text)
}

export function workflowPhaseLabel(phase: string): string {
  const map: Record<string, string> = {
    ideation: '写作流程：构思',
    outlining: '写作流程：提纲',
    drafting: '写作流程：起草',
    revising: '写作流程：修订',
    polishing: '写作流程：润色',
    complete: '写作流程：完成',
  }
  return map[phase] || `写作流程：${businessText(phase)}`
}

export function localizeStatusWords(text: string): string {
  return text
    .replace(/\bDone\.?\b/g, '已完成')
    .replace(/\bdone\.?\b/g, '已完成')
    .replace(/\bOK\b/g, '成功')
    .replace(/\bok\b/g, '成功')
    .replace(/\bcompleted\b/g, '已完成')
    .replace(/^Goal:\s*/i, '目标：')
}

export function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`
  const seconds = Math.round(ms / 100) / 10
  return `${seconds}s`
}

export type RuntimeActivityGroup = 'plan' | 'agent' | 'tool' | 'file' | 'verify' | 'git' | 'reply' | 'decision' | 'system'

export const activityGroupMeta: Record<RuntimeActivityGroup, string> = {
  plan: '理解与规划',
  agent: '设计与 Agent',
  tool: '工具执行',
  file: '文件改动',
  verify: '验证检查',
  git: '版本记录',
  reply: '整理回复',
  decision: '等待确认',
  system: '运行状态',
}

export const activityGroupOrder: RuntimeActivityGroup[] = ['plan', 'agent', 'tool', 'file', 'verify', 'git', 'reply', 'decision', 'system']
