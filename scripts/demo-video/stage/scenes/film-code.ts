/* 成片「实现功能」段：真实前端跑真实对话。
 *
 * 内容全部来自真实录制（小游戏那一趟）：需求原话、真实文件路径、真实工具调用、
 * 收尾原话，以及它写出来的真实源码（放进回答里，产品自己会渲染成代码块）。
 */

import { ease, seg, reveal, type StageScene } from '../src/timeline'
import { snapshotAt, type Turn } from '../src/snapshot'

const THREAD = 'film-code'
const BASE = '2026-10-05T21:20:00.000Z'

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
  title: '实现经营建造小游戏',
  status: 'idle',
  created_at: BASE,
  updated_at: BASE,
  metadata: {
    work_root: PROJECT.work_root,
    model_id: 'demo-model',
    runtime_preferences: { permission_preset: 'full_access' },
  },
}

const PROMPT = '在当前目录创建 game/index.html：一个单文件、双击就能玩的经营建造小游戏。'
const TYPE_FROM = 0.3
const TYPE_CPS = 70
const SEND_AT = 1.6

const WORD_CPS = 120
const ROW_CPS = 70
const ANSWER_AT = 6.2

// 真实源码（game/js/sim.js 的核心循环）+ 它收尾时说的原话
const ANSWER = [
  '先看一遍项目目录，确认工具链和 `game/` 是否存在，然后把模拟那一层写出来：',
  '',
  '```js',
  'function step(world, dt) {',
  '  if (dt > 0) world.time += dt;',
  '  updatePhase(world);              // 昼夜相位',
  '  computeConnectivity(world);      // 道路连通',
  '  world.pop.cap = World.popCapNow(world);',
  '  if (dt <= 0) return;',
  '',
  '  let aura = 1, taxMult = 1;',
  '  for (const t of world.tiles) {',
  '    const b = t.bld;',
  '    if (!b || !b.connected) continue;',
  '    const e = CONFIG.buildings[b.type].effect;',
  '    if (e.auraProd) aura += e.auraProd * World.levelMult(b.level);',
  '  }',
  '}',
  '```',
  '',
  '地块网格、资源循环、建造菜单和昼夜都在跑了，两张截图我也看过画面。',
].join('\n')

const TURNS: Turn[] = [
  {
    id: 'build-game',
    at: SEND_AT,
    prompt: PROMPT,
    steps: [
      { kind: 'thinking', at: 1.8, text: '先把工程立起来：一个格子的世界、一套资源循环，再让它自己动。', cps: ROW_CPS },
      {
        kind: 'tool',
        at: 2.6,
        text: 'game/js/sim.js',
        cps: ROW_CPS,
        title: '写模拟推进：生产、消费、人口、昼夜',
        tool: 'write_file',
        args: { path: 'game/js/sim.js' },
      },
      {
        kind: 'tool',
        at: 3.4,
        text: 'game/js/render.js',
        cps: ROW_CPS,
        title: '写等距绘制',
        tool: 'write_file',
        args: { path: 'game/js/render.js' },
      },
      {
        kind: 'tool',
        at: 4.2,
        text: 'game/js/ui.js',
        cps: ROW_CPS,
        title: '写资源条与建造菜单',
        tool: 'write_file',
        args: { path: 'game/js/ui.js' },
      },
      {
        kind: 'tool',
        at: 5.0,
        text: 'node tools/shot.mjs --out game/.verify/game-day.png',
        cps: ROW_CPS,
        title: '截图自检',
        tool: 'run_command',
        args: { command: 'node tools/shot.mjs --out game/.verify/game-day.png' },
      },
      { kind: 'answer', at: ANSWER_AT, text: ANSWER, cps: WORD_CPS },
    ],
  },
]

// 答完之后切到产品自己的「定时任务」那一屏：时间/钟点/定时这件事由产品来画
const ARRANGE_AT = 11.4
let openedArrange = false

export default {
  id: 'film-code',
  duration: 15.0,

  frame(t) {
    if (!openedArrange && t >= ARRANGE_AT) {
      openedArrange = true
      const doc = (document.querySelector('iframe') as HTMLIFrameElement | null)?.contentDocument
      doc?.querySelectorAll('[data-rail-entry="arrange"]').forEach((el) => (el as HTMLElement).click())
    }
    // 窗口就是这一栏本身：片子的镜头（缓慢推近）由成片那边给，这里不再自己缩放
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
        idPrefix: 'film-code',
      }),
    }
  },
} satisfies StageScene
