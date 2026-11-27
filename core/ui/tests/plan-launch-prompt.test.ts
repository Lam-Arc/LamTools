import { describe, expect, it } from 'vitest'

import { buildPlanLaunchPrompt } from '../src/app/planLaunch'
import type { CorePlanLibraryEntry } from '../src/projects/client'

/**
 * 从方案发起任务（PRD §7.4 / §9.1）：每个动作都要把「哪份方案、在哪、做什么」
 * 讲清楚，让新会话里的 Agent 先读回方案再动手；动作本身不另建执行系统。
 */

const plan = (overrides: Partial<CorePlanLibraryEntry> = {}): CorePlanLibraryEntry => ({
  name: '记忆检索.md',
  path: '方案/记忆检索.md',
  folder: '',
  title: '记忆检索机制',
  status: 'ready',
  design_status: 'active',
  impl_status: 'none',
  type: 'SPEC',
  type_label: '技术规范',
  topic: 'Sunday Memory',
  related: [],
  summary: '检索协议与边界',
  favorite: false,
  size: 200,
  updated_at: 1759200000,
  ...overrides,
})

const local = { sameProject: true }

describe('从方案发起任务', () => {
  it('讨论、审查、修订、检查各有自己的要求，且都先读回方案', () => {
    const discuss = buildPlanLaunchPrompt('discuss', plan(), local)
    const review = buildPlanLaunchPrompt('review', plan(), local)
    const revise = buildPlanLaunchPrompt('revise', plan(), local)
    const check = buildPlanLaunchPrompt('check', plan(), local)

    for (const prompt of [discuss, review, revise, check]) {
      expect(prompt).toContain('记忆检索机制')
      expect(prompt).toContain('方案/记忆检索.md')
      expect(prompt).toContain('read_file')
      // 修订永远改现有文件，不另建一份（A06）。
      expect(prompt).toContain('不要另建一份')
    }

    expect(discuss).toContain('和我讨论')
    expect(review).toContain('可执行性')
    expect(review).toContain('问题写回方案')
    expect(revise).toContain('只改要求的部分')
    expect(check).toContain('PASS')
    expect(check).toContain('没有证据的不算完成')
  })

  it('开工 / 实施走执行流程：读回方案、核对现状、装清单再开工', () => {
    const start = buildPlanLaunchPrompt('start', plan(), local)
    const execute = buildPlanLaunchPrompt('execute', plan(), local)

    for (const prompt of [start, execute]) {
      expect(prompt).toContain('execute-plan')
      expect(prompt).toContain('清单')
      expect(prompt).toContain('对照仓库现状')
    }
  })

  it('跨项目时说明方案属于哪个项目、绝对位置，以及需要申请访问批准', () => {
    const prompt = buildPlanLaunchPrompt('review', plan(), {
      sameProject: false,
      projectName: 'Sunday Memory',
      absolutePath: 'D:/Work/Sunday/方案/记忆检索.md',
    })

    expect(prompt).toContain('Sunday Memory')
    expect(prompt).toContain('D:/Work/Sunday/方案/记忆检索.md')
    expect(prompt).toContain('访问批准')
  })
})
