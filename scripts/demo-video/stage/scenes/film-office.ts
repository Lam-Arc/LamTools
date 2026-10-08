/* 成片「办公」段：真实前端把那一趟办公干完，然后产品自己切到资料库。
 *
 * 内容全部来自真实录制（办公那一趟）：原话、真实工具调用、真实的收尾判断，
 * 以及真实的资料库条目（从演示库读出来的那一份）。
 */

import { ease, seg, reveal, clamp01, type StageScene } from '../src/timeline'
import { snapshotAt, type Turn } from '../src/snapshot'

const THREAD = 'film-office'
const BASE = '2026-10-07T23:33:00.000Z'

const PROJECT = {
  id: 'lamtools-core',
  name: 'LamTools Core',
  work_root: 'E:\\LamTools',
  icon_key: 'folder',
  color_key: 'gray',
  created_at: BASE,
  updated_at: BASE,
}

const SESSION = {
  id: THREAD,
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

// 真实原话
const PROMPT = '资料库里有 8 月的经营复盘，照那个格式把 9 月的也做一份，9 月的明细在项目里，做完存回资料库。'
const TYPE_FROM = 0.8
const TYPE_CPS = 42
const SEND_AT = 3.0

const WORD_CPS = 130
const ROW_CPS = 80
const ANSWER_AT = 9.4

// 真实收尾判断（原话节选）
const ANSWER = [
  '8 月对照确认：品类汇总行序与九月完全一致，自然流量产出比空值也是 8 月既有设计。',
  '真实差异 0 —— 55 条全部是校验器误报。收尾：存回资料库 + 更新记忆索引。',
].join('\n\n')

const TURNS: Turn[] = [
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

// 干完之后：产品自己切到资料库看一眼（真实导航，不是画出来的）
const LIBRARY_AT = 12.6
let openedLibrary = false

export default {
  id: 'film-office',
  duration: 16.0,
  libraryAt: LIBRARY_AT,

  frame(t) {
    // 到点真的去点产品自己的导航按钮：资料库这一屏由产品渲染，不是我画的
    if (!openedLibrary && t >= LIBRARY_AT) {
      openedLibrary = true
      const doc = (document.querySelector('iframe') as HTMLIFrameElement | null)?.contentDocument
      doc?.querySelectorAll('[data-rail-entry="library"]').forEach((el) => (el as HTMLElement).click())
    }
    return {
      rect: { x: 0, y: 0, w: 1120, h: 888, radius: 0 },
      overlay: '',
      caption: { title: '', hint: '' },
    }
  },

  data(t, revision) {
    return {
      projects: [PROJECT],
      sessions: [SESSION],
      threadId: THREAD,
      theme: 'light' as const,
      composerDraft: t < SEND_AT ? reveal(PROMPT, t, TYPE_FROM, TYPE_CPS) : '',
      snapshot: snapshotAt(TURNS, t, {
        threadId: THREAD,
        revision,
        baseTime: BASE,
        idPrefix: 'film-office',
      }),
    }
  },
} satisfies StageScene
