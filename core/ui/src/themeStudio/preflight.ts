/**
 * 发布前响应式检查。
 *
 * user:“发布前执行连续宽度扫描和关键节点可达性检查，列出冲突/溢出/过小触控区域”+
 * (在几个代表宽度上量一遍已登记元素：超出外壳、关键入口量不到、触控区过小。
 *  纯计算部分放在这里，读 DOM 的部分由编辑器调用，便于单独测试。)
 */

export type PreflightIssueKind = 'overflow' | 'unreachable' | 'touch-target'

export interface PreflightRect {
  left: number
  top: number
  width: number
  height: number
}

export interface PreflightTarget {
  id: string
  label: string
  /** 注册表里的保护级别；protected 是业务入口，不允许量不到。 */
  protection: 'editable' | 'appearance-only' | 'protected'
  /** 这个元素是否允许改尺寸（允许改却小到点不到，才是问题）。 */
  editableSize: boolean
  rect: PreflightRect
}

export interface PreflightIssue {
  id: string
  label: string
  kind: PreflightIssueKind
  /** 问题最明显的那个宽度（断点区间按窄的算）。 */
  width: number
  message: string
}

/** 代表宽度：从宽到窄，覆盖计划里点名的 320/375/768/1024/1440。 */
export const PREFLIGHT_WIDTHS = [1440, 1024, 768, 375, 320] as const
/** 触控目标下限：低于这个尺寸在窄屏上点不中。 */
export const PREFLIGHT_MIN_TOUCH = 20
/** 溢出容差：亚像素取整不该被当成越界。 */
const EDGE_TOLERANCE = 1

export interface PreflightSample {
  width: number
  shell: PreflightRect
  targets: PreflightTarget[]
}

function edgeOverflow(rect: PreflightRect, shell: PreflightRect): string[] {
  const edges: string[] = []
  if (rect.left < shell.left - EDGE_TOLERANCE) edges.push(`左 ${Math.round(shell.left - rect.left)}px`)
  const right = rect.left + rect.width
  const bottom = rect.top + rect.height
  if (right > shell.left + shell.width + EDGE_TOLERANCE) {
    edges.push(`右 ${Math.round(right - (shell.left + shell.width))}px`)
  }
  if (rect.top < shell.top - EDGE_TOLERANCE) edges.push(`上 ${Math.round(shell.top - rect.top)}px`)
  if (bottom > shell.top + shell.height + EDGE_TOLERANCE) {
    edges.push(`下 ${Math.round(bottom - (shell.top + shell.height))}px`)
  }
  return edges
}

/** 单个宽度下的一遍检查。 */
export function checkTargetsAtWidth(sample: PreflightSample): PreflightIssue[] {
  const issues: PreflightIssue[] = []
  for (const target of sample.targets) {
    const { rect } = target
    const edges = edgeOverflow(rect, sample.shell)
    if (edges.length) {
      issues.push({
        id: target.id,
        label: target.label,
        kind: 'overflow',
        width: sample.width,
        message: `${target.label} 在 ${sample.width}px 宽下超出界面 ${edges.join('、')}`,
      })
    }
    const unmeasurable = rect.width < 1 || rect.height < 1
    if (unmeasurable && target.protection === 'protected') {
      issues.push({
        id: target.id,
        label: target.label,
        kind: 'unreachable',
        width: sample.width,
        message: `${target.label} 是业务入口，但在 ${sample.width}px 宽下量不到（被隐藏或没有尺寸）`,
      })
    }
    if (!unmeasurable && target.editableSize
      && (rect.width < PREFLIGHT_MIN_TOUCH || rect.height < PREFLIGHT_MIN_TOUCH)) {
      issues.push({
        id: target.id,
        label: target.label,
        kind: 'touch-target',
        width: sample.width,
        message: `${target.label} 在 ${sample.width}px 宽下只有 ${Math.round(rect.width)}×${Math.round(rect.height)}，点不中`,
      })
    }
  }
  return issues
}

/**
 * 多宽度汇总：同一个元素同一种问题只报一次，取最窄的那次（最坏情况）。
 * 溢出与不可达阻断发布，触控过小只警告。
 */
export function collectIssues(samples: PreflightSample[]): PreflightIssue[] {
  const worst = new Map<string, PreflightIssue>()
  for (const sample of samples) {
    for (const issue of checkTargetsAtWidth(sample)) {
      const key = `${issue.id}:${issue.kind}`
      const existing = worst.get(key)
      if (!existing || issue.width < existing.width) worst.set(key, issue)
    }
  }
  return [...worst.values()].sort((left, right) => {
    const order: Record<PreflightIssueKind, number> = { unreachable: 0, overflow: 1, 'touch-target': 2 }
    return order[left.kind] - order[right.kind] || left.width - right.width
  })
}

/** 阻断发布的只有溢出与关键入口不可达；触控过小是提醒。 */
export function blockingIssues(issues: PreflightIssue[]): PreflightIssue[] {
  return issues.filter((issue) => issue.kind !== 'touch-target')
}

export interface ScanShell {
  style: { width: string }
  offsetWidth: number
}

/**
 * 在一个任务里把外壳依次压到各宽度并取样，结束时恢复原宽度。
 *
 * 整个过程同步完成，浏览器不会把中间宽度画出来，用户看不到闪动。
 * 只改 style.width，不碰业务状态；异常时也一定恢复。
 */
export function scanShellWidths(
  shell: ScanShell,
  widths: readonly number[],
  measure: (width: number) => Omit<PreflightSample, 'width'>,
): PreflightSample[] {
  const original = shell.style.width
  const samples: PreflightSample[] = []
  try {
    for (const width of widths) {
      shell.style.width = `${width}px`
      // 强制同步布局，让下一次测量拿到新宽度。
      void shell.offsetWidth
      samples.push({ width, ...measure(width) })
    }
  } finally {
    shell.style.width = original
    void shell.offsetWidth
  }
  return samples
}
