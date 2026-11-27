import { t } from '@/i18n/index.ts'
import type { PlanAction, PlanLibraryEntry } from '@/components/PlanLibraryView.vue'

/**
 * 从方案发起 Agent 任务时的提示词（PRD §7.4 / §9.1）。
 *
 * 动作本身只是一句话，真正的能力仍由方案 Skill（draft-plan / refine-plan /
 * execute-plan 与 plan-docs 的类型规范）承担；这里只负责把「哪一份方案、
 * 在什么位置、要做什么」讲清楚，让 Agent 在新会话里能自己读回方案继续工作。
 */
export type PlanLaunchAction = PlanAction | 'start'

export interface PlanLaunchLocation {
  /** 方案与目标会话在同一个项目里（库内路径就是可读路径）。 */
  sameProject: boolean
  /** 跨项目时方案所属的项目名。 */
  projectName?: string
  /** 跨项目时方案的绝对路径。 */
  absolutePath?: string
}

const ACTIONS: Record<Exclude<PlanLaunchAction, 'start' | 'execute'>, () => string> = {
  discuss: () => t("围绕它的目标、范围、约束与未答问题和我讨论；没定的事先问，不要替我拍板。"),
  review: () => t("审查它的目标、范围、约束与可执行性，指出遗漏、矛盾与过度设计；有问题写回方案或同专题的审查记录，不只给口头评价。"),
  revise: () => t("按我这次的要求修订它：只改要求的部分，其余保持原样；有冲突的地方一并修正并告诉我。"),
  check: () => t("对照它核实实际落实情况：检查文件、测试与运行结果，逐条给出 PASS / PARTIAL / FAIL / UNVERIFIED / BLOCKED 和证据；没有证据的不算完成。"),
}

export function buildPlanLaunchPrompt(
  action: PlanLaunchAction,
  plan: PlanLibraryEntry,
  location: PlanLaunchLocation,
): string {
  const where = location.sameProject
    ? t("先用 read_file 读回这份方案（{0}）。", { 0: plan.path })
    : t("先用 read_file 读回这份方案，它属于项目「{0}」，存放在 {1}（当前项目之外，读取需要先申请访问批准）。", {
        0: location.projectName || '',
        1: location.absolutePath || plan.path,
      })
  const work = action === 'start' || action === 'execute'
    ? t("对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。")
    : ACTIONS[action]()
  return [
    t("处理方案《{0}》。", { 0: plan.title }),
    where,
    work,
    t("方案文件的修改写回它原来的位置，不要另建一份。"),
  ].join('')
}
