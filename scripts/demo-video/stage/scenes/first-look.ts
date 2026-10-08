/* First look at the stage: the real application, drawn by time.
 *
 * Two things this scene is here to prove:
 *   1. the product renders — a typed message, a live turn with thinking, a
 *      tool call, a command and a streaming answer, all from the snapshot;
 *   2. the product is responsive — the window narrows and the application
 *      re-lays itself out for real, because it is really laying itself out.
 *
 * Times are on the same 100 BPM grid as the motion scenes: beat 0.6s.
 */

import { cursorHtml, ease, reveal, seg, type StageScene } from '../src/timeline'
import { snapshotAt, type Turn } from '../src/snapshot'

const THREAD = 'stage-thread'
const BASE = '2026-10-06T08:00:00.000Z'

const PROJECT = {
  id: 'lamtools-core',
  name: 'LamTools Core',
  work_root: 'E:\\LamTools',
  icon_key: 'code',
  color_key: 'cyan',
  created_at: BASE,
  updated_at: BASE,
}

const SESSION = {
  id: THREAD,
  title: '把上周的数据整理成周报',
  status: 'idle',
  created_at: BASE,
  updated_at: BASE,
  metadata: {
    work_root: PROJECT.work_root,
    model_id: 'demo-model',
    runtime_preferences: { permission_preset: 'ask' },
  },
}

const PROMPT = '把上周的数据整理成一份周报，按上次的格式'
// 自己打字：保持人手速度（快了不像人在打）
const TYPE_FROM = 1.2
const TYPE_CPS = 14
const SEND_AT = 3.4

// 它出字：比阅读速度再快一截。片子里的文字是"落下来"的，不是让人等着读完的。
const WORD_CPS = 76
const ROW_CPS = 60

const ANSWER = [
  '上周的阅读量是 12.4 万，比前一周高 18%，主要来自周三那篇。',
  '留存没有明显变化，但新用户的次日回访掉了 3 个百分点，我把它单独列出来了 —— 这一项建议下周再看一次。',
  '整份周报已经按你上次的格式做好，放在项目目录的 reports/ 里。',
].join('')

const TURNS: Turn[] = [
  {
    id: 'one',
    at: SEND_AT,
    prompt: PROMPT,
    steps: [
      {
        kind: 'thinking',
        at: 3.6,
        text: '先看上周的数据放在哪、上次那份周报是什么结构，再照着写。',
        cps: ROW_CPS,
      },
      {
        kind: 'tool',
        at: 4.4,
        text: 'reports/2026-09-28-weekly.md',
        cps: ROW_CPS,
        title: '读取上次的周报',
        tool: 'read_file',
        args: { path: 'reports/2026-09-28-weekly.md' },
      },
      {
        kind: 'tool',
        at: 5.2,
        text: 'tools/weekly.py',
        cps: ROW_CPS,
        title: '汇总上周数据',
        tool: 'run_command',
        args: { command: 'python tools/weekly.py --from 2026-09-28' },
      },
      {
        kind: 'answer',
        at: 6.0,
        text: ANSWER,
        cps: WORD_CPS,
      },
    ],
  },
]

const NARROW_FROM = 9.0
const NARROW_TO = 11.0

export default {
  id: 'first-look',
  duration: 15,

  frame(t) {
    // the window the film frames the product in; it narrows once, on purpose
    const narrow = ease.sineInOut(seg(t, NARROW_FROM, NARROW_TO))
    const widen = ease.sineInOut(seg(t, NARROW_TO + 0.6, NARROW_TO + 2.4))
    const w = 1680 - 600 * (narrow - widen)
    const h = 888 - 64 * (narrow - widen)
    const x = 120
    const y = 96
    return {
      rect: { x, y, w, h, radius: 20 },
      overlay: cursorHtml(cursor(t, x, y, w, h)),
      caption: {
        title: captionTitle(t),
        hint: t < NARROW_FROM
          ? '真实前端：消息、思考、工具调用、命令、流式回答全部由快照驱动'
          : '同一个窗口变窄：应用按真实布局重排，不是把画面缩小',
      },
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
        idPrefix: 'stage',
      }),
    }
  },
} satisfies StageScene

/** The cursor is scenery: the state change is what actually sends the turn. */
function cursor(t: number, x: number, y: number, w: number, h: number) {
  const from = { x: x + 420, y: y + h - 210 }
  const to = { x: x + w - 74, y: y + h - 62 }
  const travel = ease.sineInOut(seg(t, SEND_AT - 0.9, SEND_AT - 0.15))
  const press = Math.sin(Math.PI * seg(t, SEND_AT - 0.15, SEND_AT + 0.18))
  const alpha = seg(t, SEND_AT - 1.1, SEND_AT - 0.85) * (1 - seg(t, SEND_AT + 0.3, SEND_AT + 0.7))
  return {
    x: from.x + (to.x - from.x) * travel,
    y: from.y + (to.y - from.y) * travel,
    press: Math.max(0, press),
    alpha,
  }
}

function captionTitle(t: number) {
  if (t < TYPE_FROM) return '窗口摆好'
  if (t < SEND_AT) return '把话说进输入框'
  if (t < 6.0) return '它开始干活'
  if (t < NARROW_FROM) return '一句一句写出来'
  return '换个宽度'
}
