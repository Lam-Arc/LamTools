/* 办公段的公共内容：真实录制里的原话、真实工具调用、真实收尾判断。
 * 三个窄栏场景（聊天 / 资料库-分层 / 资料库-文件）共用这一份。 */

import { type StageScene, type SceneData } from '../src/timeline'
import { snapshotAt, type Turn } from '../src/snapshot'

export const BASE = '2026-10-07T23:33:00.000Z'

export const PROJECT = {
  id: 'lamtools-core',
  name: 'LamTools Core',
  work_root: 'E:\\LamTools',
  icon_key: 'folder',
  color_key: 'gray',
  created_at: BASE,
  updated_at: BASE,
}

export const SESSION = {
  id: 'film-office',
  title: '制作 9 月经营复盘',
  status: 'idle',
  created_at: BASE,
  updated_at: BASE,
  metadata: {
    work_root: PROJECT.work_root,
    model_id: 'demo-model',
    runtime_preferences: { permission_preset: 'full_edit' },
  },
}

export const PROMPT = '资料库里有 8 月的经营复盘，照那个格式把 9 月的也做一份，9 月的明细在项目里，做完存回资料库。'
export const TYPE_FROM = 0.8
export const TYPE_CPS = 42
export const SEND_AT = 3.0

const WORD_CPS = 130
const ROW_CPS = 80
const ANSWER_AT = 9.4

const ANSWER = [
  '8 月对照确认：品类汇总行序与九月完全一致，自然流量产出比空值也是 8 月既有设计。',
  '真实差异 0 —— 55 条全部是校验器误报。收尾：存回资料库 + 更新记忆索引。',
].join('\n\n')

export const TURNS: Turn[] = [
  {
    id: 'monthly-review',
    at: SEND_AT,
    prompt: PROMPT,
    steps: [
      { kind: 'thinking', at: 3.2, text: '读 8 月的复盘，取它的结构与口径。', cps: ROW_CPS },
      {
        kind: 'tool',
        at: 4.2,
        text: '复盘/经营复盘索引.md',
        cps: ROW_CPS,
        title: '从资料库取上一个月的口径',
        tool: 'memory',
        args: { action: 'read', scope: 'project', path: '复盘/经营复盘索引.md' },
      },
      {
        kind: 'tool',
        at: 5.4,
        text: '经营数据/2026-09-经营明细.csv',
        cps: ROW_CPS,
        title: '核算 9 月明细：渠道、品类、退款',
        tool: 'run_command',
        args: { command: 'head -5 经营数据/2026-09-经营明细.csv' },
      },
      {
        kind: 'tool',
        at: 6.6,
        text: '经营复盘/2026-09-月度汇总表.xlsx',
        cps: ROW_CPS,
        title: '出月度汇总表',
        tool: 'write_file',
        args: { path: '经营复盘/2026-09-月度汇总表.xlsx' },
      },
      {
        kind: 'tool',
        at: 7.8,
        text: '经营复盘/2026-09-经营复盘.pptx',
        cps: ROW_CPS,
        title: '出 11 页复盘（图表为主）',
        tool: 'write_file',
        args: { path: '经营复盘/2026-09-经营复盘.pptx' },
      },
      { kind: 'answer', at: ANSWER_AT, text: ANSWER, cps: WORD_CPS },
    ],
  },
]

/** 走完对话之后，真的去点产品自己的导航：先把资料库打开，再点某个页签。 */
export function useLibrary(t: number, tab: '资料' | '文件夹'): void {
  const key = tab === '文件夹' ? 'folders' : 'files'
  const state = (useLibrary as unknown as { _state?: Record<string, boolean> })._state
    || ((useLibrary as unknown as { _state: Record<string, boolean> })._state = {})
  if (state[key]) return
  state[key] = true
  const doc = (document.querySelector('iframe') as HTMLIFrameElement | null)?.contentDocument
  if (!doc) return
  const rail = doc.querySelector('[data-rail-entry="library"]') as HTMLElement | null
  rail?.click()
  // 页签是产品自己的控件：资料 / 记忆 / 方案 三选一，这里点“资料”
  const tabs = doc.querySelectorAll('button')
  tabs.forEach((node) => {
    if ((node.textContent || '').trim() === '资料') (node as HTMLElement).click()
  })
  if (tab === '文件夹') {
    // 资料这一页里的“文件夹”页签（分层）
    setTimeout(() => {
      const again = (document.querySelector('iframe') as HTMLIFrameElement | null)?.contentDocument
      again?.querySelectorAll('[data-materials-tab="folders"]').forEach((node) => (node as HTMLElement).click())
    }, 0)
  }
}

/** 窄栏场景的公共 data()：内容是同一份对话。 */
export function officeData(t: number, revision: number, prefix: string): SceneData {
  return {
    projects: [PROJECT],
    sessions: [SESSION],
    threadId: SESSION.id,
    theme: 'light' as const,
    composerDraft: '',
    snapshot: snapshotAt(TURNS, t, { threadId: SESSION.id, revision, baseTime: BASE, idPrefix: prefix }),
  }
}

export type { StageScene }
