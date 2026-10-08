/*
 * 演示视频 · 林溪小镇「活着的村子」桥段 —— 逐帧渲染
 * =====================================================================
 * 输出：1920x1080 @ 30fps，450 帧（15.0 s）f0001.png … f0450.png
 *
 *   node scripts/demo-video/game/render.mjs                       # 出整段 + 复核静帧
 *   node scripts/demo-video/game/render.mjs --out=E:/tmp/x        # 换输出目录
 *   node scripts/demo-video/game/render.mjs --from=250 --to=300   # 只落这一段（前面照样推演）
 *   node scripts/demo-video/game/render.mjs --no-review           # 不出复核静帧
 *
 * 时间表（帧号从 0 起，文件名 = 帧号 + 1）
 *   0   … 149   建立：白天，镜头缓慢横移 + 推近
 *   150 … 299   交互：建造栏选卡 → 落民居 → 选农田 → 落农田
 *   300 … 449   生活：2× 推进模拟，资源跳动，傍晚降临、窗户亮起
 *
 * 确定性：见 director.js。本脚本只按固定顺序调用 __pump / mouse / key，
 * 因此同一帧两次渲染逐字节相同。
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  launch, openGame, pumpTo, warmup, camAt, tileCenter, ensureDir, frameName,
  dirSize, human, FPS, TOTAL_FRAMES, OUT_ROOT, VIEW_W, VIEW_H, WARMUP_FRAMES,
} from './lib.mjs';

// ------------------------------------------------------------------ 参数
const argv = process.argv.slice(2);
function arg(name, def) {
  const hit = argv.find((a) => a === '--' + name || a.startsWith('--' + name + '='));
  if (!hit) return def;
  const i = hit.indexOf('=');
  return i < 0 ? true : hit.slice(i + 1);
}
const SEED = parseInt(arg('seed', '2024'), 10);
const TOD = parseFloat(arg('tod', '0.45'));      // 开局时刻：白天偏午后（整段走到夜里）
const PHASE3_SPEED = parseFloat(arg('speed3', '4')); // 生活段速度（游戏自带 1/2/4×）
const FRAME_DIR = String(arg('out', path.join(OUT_ROOT, 'frames')));
const REVIEW_DIR = String(arg('review', path.join(OUT_ROOT, 'review')));
const FROM = parseInt(arg('from', '0'), 10);
const TO = parseInt(arg('to', String(TOTAL_FRAMES - 1)), 10);
const ONLY_ARG = arg('only', null);
// --only=30,180,360 ：只落这几帧（前面照样整段推演）——确定性比对用
const ONLY = ONLY_ARG ? new Set(String(ONLY_ARG).split(',').map((n) => parseInt(n, 10))) : null;
const NEED_REVIEW = !arg('no-review', false);
const QUIET = !!arg('quiet', false);

const log = (...a) => { if (!QUIET) console.log(...a); };

// ------------------------------------------------------------------ 分镜
// 阶段边界（0 起的帧号）
const F_ESTABLISH_END = 150;   // 0..149   建立：镜头缓慢横移 + 推近
const F_INTERACT_END = 300;    // 150..299 交互：选卡 → 落民居
// 300..449 生活：2× 推进，傍晚降临

// 交互关键帧（鼠标 / 点击）；「悬停」段必须让指针停在目标上，点击只发生在悬停段内
const F_CARD_HOUSE_IN = 150;   // 指针从画外走向「民居」卡片
const F_CARD_HOUSE_H1 = 165;   // 悬停民居（提示牌：民居 / 造价 25 木 / 需紧邻道路）
const F_CARD_HOUSE_H1_END = 182;
const F_CARD_FARM_H = 189;     // 悬停农田
const F_CARD_FARM_H_END = 206;
const F_CARD_ROAD_H = 213;     // 悬停道路
const F_CARD_ROAD_H_END = 228;
const F_CARD_HOUSE_H2 = 233;   // 回到民居
const F_CARD_HOUSE_H2_END = 261;
const F_PICK_HOUSE = 253;      // 点选民居（指针静止在卡片中心）
const F_PLOT_HOUSE_IN = 263;   // 指针走向民居地块（幽灵预览跟随）
const F_PLOT_HOUSE_H = 285;    // 停在地块上，等幽灵预览看清
const F_PLACE_HOUSE = 297;     // 左键落下 → 民居建成
const F_LIFE_START = 300;      // 收工具、指针移出画布（场面清干净）
const F_SPEED_UP = 320;        // 再切 4×（先留 0.8 s 让「民居 ✓」漂字被看清）

// 相机锚点（世界地块坐标 + 缩放）；锚点间 smoothstep，绝无抖动
let CAM = null; // 依据村庄中心在运行时生成
function buildCam(vc, housePlot) {
  return [
    { f: 0, cx: vc.x - 1.8, cy: vc.y + 1.2, z: 1.30 },
    { f: 90, cx: vc.x - 0.7, cy: vc.y + 0.8, z: 1.48 },
    { f: F_ESTABLISH_END - 1, cx: vc.x + 0.3, cy: vc.y + 0.5, z: 1.62 },
    { f: 225, cx: vc.x + 0.5, cy: vc.y + 0.4, z: 1.68 },
    { f: F_PLOT_HOUSE_H, cx: housePlot.x - 0.5, cy: housePlot.y + 0.6, z: 1.78 },
    { f: 365, cx: vc.x + 0.9, cy: vc.y + 0.3, z: 1.66 },
    { f: TOTAL_FRAMES - 1, cx: vc.x + 0.4, cy: vc.y + 1.3, z: 1.42 },
  ];
}

// ------------------------------------------------------------------ 指针时间表
// 目标点：{kind:'abs', x, y} 固定屏幕像素 / {kind:'tile', x, y} 地块中心
function smooth(t) { return t * t * (3 - 2 * t); }

function makePointerKeys(cards, plots) {
  const OFF = { kind: 'abs', x: 1, y: 1 }; // 画布外（顶栏空白处），不产生悬停
  const C = (t) => ({ kind: 'abs', x: cards[t].cx, y: cards[t].cy });
  const T = (p) => ({ kind: 'tile', x: p.x, y: p.y });
  // 每段：移动（两端）+ 悬停（两端相同 → 指针静止，点击只发生在静止段）
  return [
    { f: 0, p: OFF },
    { f: F_CARD_HOUSE_IN - 1, p: OFF },
    { f: F_CARD_HOUSE_H1, p: C('house') },
    { f: F_CARD_HOUSE_H1_END, p: C('house') },
    { f: F_CARD_FARM_H, p: C('farm') },
    { f: F_CARD_FARM_H_END, p: C('farm') },
    { f: F_CARD_ROAD_H, p: C('road') },
    { f: F_CARD_ROAD_H_END, p: C('road') },
    { f: F_CARD_HOUSE_H2, p: C('house') },
    { f: F_CARD_HOUSE_H2_END, p: C('house') },
    { f: F_PLOT_HOUSE_IN, p: T(plots.house) },
    { f: F_PLACE_HOUSE + 1, p: T(plots.house) },
    { f: F_LIFE_START + 1, p: OFF },
    { f: TOTAL_FRAMES - 1, p: OFF },
  ];
}

function resolvePointer(target, cam) {
  if (target.kind === 'tile') return tileCenter(target.x, target.y, cam);
  return { x: target.x, y: target.y };
}

function pointerAt(keys, f, cam) {
  if (f <= keys[0].f) return resolvePointer(keys[0].p, cam);
  const lastK = keys[keys.length - 1];
  if (f >= lastK.f) return resolvePointer(lastK.p, cam);
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (f >= a.f && f <= b.f) {
      const t = smooth((f - a.f) / Math.max(1, b.f - a.f));
      const A = resolvePointer(a.p, cam);
      const B = resolvePointer(b.p, cam);
      return { x: A.x + (B.x - A.x) * t, y: A.y + (B.y - A.y) * t };
    }
  }
  return resolvePointer(lastK.p, cam);
}

// ------------------------------------------------------------------ 主流程
const outDir = ensureDir(FRAME_DIR);
const revDir = ensureDir(REVIEW_DIR);
if (FROM === 0 && TO === TOTAL_FRAMES - 1 && !ONLY) {
  // 全量重渲时清掉上次留下的、不在本次命名范围内的帧（只动本脚本自己的产物）
  const keep = new Set();
  for (let i = 1; i <= TOTAL_FRAMES; i++) keep.add(frameName(i));
  let removed = 0;
  for (const f of fs.readdirSync(outDir)) {
    if (/^f\d+\.png$/.test(f) && !keep.has(f)) { fs.unlinkSync(path.join(outDir, f)); removed++; }
  }
  if (removed) log(`[frames] 清理陈旧帧 ${removed} 张`);
}

// 复核静帧取样帧（0 起）
const REVIEW_PICKS = [
  ['1-establish', 60],
  ['2-build-menu', 200],
  ['3-placement-done', 310],
  ['4-life-dusk', 432],
];
const reviewAt = new Map(REVIEW_PICKS.map(([n, f]) => [f, n]));

const browser = await launch();
const { context, page, pageErrors } = await openGame(browser, { seed: SEED, tod: TOD });

// ---- 事实探针：村庄中心、可建地块、建造栏卡片位置 ----------------------
const facts = await page.evaluate(() => {
  const g = window.__game;
  const Wd = window.World;
  const w = g.world;
  const vc = w.village || { x: 12, y: 12 };

  // 可建且无警告（= 紧邻道路）的空地，按「离村中心近 → y → x」稳定排序
  function plots(type) {
    const out = [];
    for (let y = 0; y < w.h; y++) {
      for (let x = 0; x < w.w; x++) {
        const chk = Wd.canBuild(w, type, x, y);
        if (!chk.ok || (chk.warnings && chk.warnings.length)) continue;
        const t = Wd.at(w, x, y);
        if (!t || t.terrain !== 'grass' || t.tree || t.rock || t.bld) continue;
        out.push({ x, y, d: Math.max(Math.abs(x - vc.x), Math.abs(y - vc.y)) });
      }
    }
    out.sort((a, b) => (a.d - b.d) || (a.y - b.y) || (a.x - b.x));
    return out;
  }
  const hp = plots('house');
  const fp = plots('farm');

  // 建造栏卡片中心
  const cards = {};
  for (const el of document.querySelectorAll('.build-card')) {
    const r = el.getBoundingClientRect();
    cards[el.dataset.type] = { cx: r.left + r.width / 2, cy: r.top + r.height / 2, w: r.width, h: r.height };
  }

  // 村落初始建筑清单（复核用）
  const blds = {};
  for (const t of w.tiles) if (t.bld) blds[t.bld.type] = (blds[t.bld.type] || 0) + 1;

  return {
    vc, hp, fp, cards, blds,
    canvas: { w: g.renderer.vw, h: g.renderer.vh, dpr: g.renderer.dpr },
    clockOk: window.__clockOk(),
    errors: window.__errors.slice(),
  };
});

if (!facts.clockOk) throw new Error('虚拟时钟未接管，确定性无从保证');
if (facts.canvas.w !== VIEW_W || facts.canvas.h !== VIEW_H) {
  throw new Error(`画布尺寸异常：${facts.canvas.w}x${facts.canvas.h}（期望 ${VIEW_W}x${VIEW_H}）`);
}
if (!facts.hp.length || !facts.fp.length) throw new Error('找不到可建地块，无法完成交互桥段');
if (!facts.cards.house || !facts.cards.farm || !facts.cards.road) {
  throw new Error('建造栏卡片缺失：' + Object.keys(facts.cards).join(','));
}

const plots = {
  // 默认地块按 seed 2024 的地图选定：紧邻道路、四周留白（幽灵预览不会被邻居建筑压住）
  house: pickPlot('house', arg('house', '11,9'), facts.hp, []),
  farm: null,
};
plots.farm = pickPlot('farm', arg('farm', '14,13'), facts.fp, [plots.house]);
CAM = buildCam(facts.vc, plots.house);

/** 显式指定地块优先（种子固定 → 构图可控），指定地块不合法时退回自动扫描结果 */
function pickPlot(type, spec, list, avoid) {
  const p = list.filter((c) => !avoid.some((a) => a.x === c.x && a.y === c.y));
  if (typeof spec === 'string' && /^\d+,\d+$/.test(spec)) {
    const [x, y] = spec.split(',').map(Number);
    const hit = p.find((c) => c.x === x && c.y === y);
    if (hit) return { x, y };
    log(`[warn] 指定地块 ${spec} 对 ${type} 不合法/被占用，改用自动扫描结果`);
  }
  if (!p.length) throw new Error(`没有可用的 ${type} 地块`);
  return { x: p[0].x, y: p[0].y };
}
const keys = makePointerKeys(facts.cards, plots);

log(`[seed ${SEED}] 村庄中心 ${facts.vc.x},${facts.vc.y}  画布 ${facts.canvas.w}x${facts.canvas.h}  预热 ${WARMUP_FRAMES} 帧  tod0=${TOD}`);
log(`[plots] 民居 ${plots.house.x},${plots.house.y}   农田 ${plots.farm.x},${plots.farm.y}`);
log(`[cards] 民居(${facts.cards.house.cx.toFixed(0)},${facts.cards.house.cy.toFixed(0)}) ` +
    `农田(${facts.cards.farm.cx.toFixed(0)},${facts.cards.farm.cy.toFixed(0)}) ` +
    `道路(${facts.cards.road.cx.toFixed(0)},${facts.cards.road.cy.toFixed(0)})`);

// ---- 离散动作（在指定帧、推帧之前执行）--------------------------------
async function clickCard(type) {
  const c = facts.cards[type];
  await page.mouse.move(round2(c.cx), round2(c.cy));
  await page.mouse.down();
  await page.mouse.up();
  return `click ${type}`;
}
function round2(n) { return Math.round(n * 100) / 100; }

const actions = new Map();
actions.set(F_PICK_HOUSE, async () => clickCard('house'));
actions.set(F_PLACE_HOUSE, async () => {
  await page.mouse.down(); await page.mouse.up();
  return `place 民居 @ ${plots.house.x},${plots.house.y}`;
});
actions.set(F_LIFE_START, async () => {
  await page.mouse.move(1, 1);
  await page.keyboard.press('Escape'); // 收起建造工具 → 不再有幽灵预览
  return 'Escape（收工具）+ 指针移出画布';
});
actions.set(F_SPEED_UP, async () => {
  await page.evaluate((sp) => {
    const g = window.__game;
    g.setSpeed(sp);
    if (g.ui && g.ui.setActiveSpeed) g.ui.setActiveSpeed(sp, g.paused);
  }, PHASE3_SPEED);
  return `切 ${PHASE3_SPEED}×`;
});

// ---- 逐帧循环 ---------------------------------------------------------
await warmup(page, camAt(CAM, 0));   // 负帧预热：起始帧就是长好的村子
await page.mouse.move(1, 1);
let lastPt = { x: 1, y: 1 };
let saved = 0;
const reviews = [];
const t0 = Date.now();

for (let f = 0; f <= TOTAL_FRAMES - 1; f++) {
  const cam = camAt(CAM, f);

  // 1) 指针
  const p = pointerAt(keys, f, cam);
  const px = round2(p.x);
  const py = round2(p.y);
  if (px !== lastPt.x || py !== lastPt.y) {
    await page.mouse.move(px, py);
    lastPt = { x: px, y: py };
  }

  // 2) 离散动作
  const act = actions.get(f);
  if (act) {
    const label = await act();
    log(`  f${String(f + 1).padStart(4, '0')}  ${label}`);
  }

  // 3) 推进一帧（dt 恒为 1/30）并让合成器提交
  await pumpTo(page, f, cam);

  // 4) 落帧
  const wantSave = ONLY ? ONLY.has(f) : (f >= FROM && f <= TO);
  if (wantSave) {
    const file = path.join(outDir, frameName(f + 1));
    await page.screenshot({ path: file, type: 'png' });
    saved++;
    if (saved % 50 === 0) log(`  … ${saved} 帧 (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  }
  if (NEED_REVIEW && reviewAt.has(f)) {
    const jpg = path.join(revDir, reviewAt.get(f) + '.jpg');
    await page.screenshot({ path: jpg, type: 'jpeg', quality: 90 });
    reviews.push({ name: reviewAt.get(f), frame: f + 1, file: jpg });
  }
}

const left = await page.evaluate(() => ({
  time: window.__game.world.time,
  tod: window.__game.world.tod,
  phase: window.__game.world.phase,
  day: window.__game.world.day,
  res: window.__game.world.res,
  speed: window.__game.speed,
  blds: (() => { const o = {}; for (const t of window.__game.world.tiles) if (t.bld) o[t.bld.type] = (o[t.bld.type] || 0) + 1; return o; })(),
  built: (() => {
    const o = [];
    for (const t of window.__game.world.tiles) {
      if (t.bld && (t.bld.type === 'house' || t.bld.type === 'farm')) o.push(`${t.bld.type}@${t.x},${t.y}L${t.bld.level}`);
    }
    return o;
  })(),
  floaters: window.__game.world.floaters.length,
  errors: window.__errors.slice(),
}));

// ---- 复核静帧 ---------------------------------------------------------
if (NEED_REVIEW && !(FROM > 0 || TO < TOTAL_FRAMES - 1)) {
  const missing = REVIEW_PICKS.filter(([, f]) => !fs.existsSync(path.join(outDir, frameName(f + 1))));
  if (missing.length) log(`[review] 缺帧：${missing.map(([n, f]) => n + '@' + (f + 1)).join(', ')}`);
}

await context.close();
await browser.close();

const size = dirSize(outDir);
log('\n================ 结果 ================');
log(`帧序列   : ${outDir}`);
log(`命名     : ${frameName(1)} … ${frameName(TOTAL_FRAMES)}  (1920x1080 @ ${FPS}fps)`);
log(`本次落帧 : ${saved}  目录内共 ${size.n} 张 / ${human(size.bytes)}`);
log(`终局状态 : time ${left.time.toFixed(2)}s  tod ${left.tod.toFixed(3)} ${left.phase}  day ${left.day}  speed ${left.speed}×`);
log(`资源     : ${JSON.stringify(left.res)}`);
log(`建筑     : ${JSON.stringify(left.blds)}`);
log(`新增落点 : ${left.built.join('  ')}`);
log(`JS 错误  : ${JSON.stringify(left.errors.concat(pageErrors || []))}`);
if (reviews.length) log(`复核静帧 : ${reviews.map((r) => r.file + ' (f' + r.frame + ')').join('  ')}`);
