/*
 * 演示视频 · 林溪小镇帧序列 · 公共工具
 * ------------------------------------
 * 只读 village-game/，不改动交付物。
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const VIEW_W = 1920;
export const VIEW_H = 1080;
export const FPS = 30;
export const TOTAL_FRAMES = 450; // 15.0 s @ 30fps

export const GAME_DIR = 'E:/LamTools/MyProject/village-game';
export const DIRECTOR = 'E:/LamTools/scripts/demo-video/game/director.js';
export const OUT_ROOT = 'E:/LamDemo/assets/game';

// 地块尺寸的一半（与 config.js CONFIG.tile = {w:64,h:32} 一致）
export const HW = 32;
export const HH = 16;

/** file:// URL + URL 调试参数（游戏自带，无需改代码） */
export function gameUrl(opts = {}) {
  const { seed = 99, tod = 0.35 } = opts;
  const u = pathToFileURL(path.join(GAME_DIR, 'index.html'));
  u.searchParams.set('nosave', '1');       // 不读档、不自动存档 → 干净且无 localStorage 依赖
  u.searchParams.set('seed', String(seed)); // 固定地图种子
  u.searchParams.set('tod', String(tod));   // 固定开局时刻
  return u.href;
}

export async function launch() {
  return chromium.launch({
    args: [
      '--force-color-profile=srgb',
      '--hide-scrollbars',
      '--disable-lcd-text',
      '--disable-features=Translate,BackForwardCache',
    ],
  });
}

/** 打开一局干净的、时钟被接管的游戏页面 */
export async function openGame(browser, opts = {}) {
  const context = await browser.newContext({
    viewport: { width: VIEW_W, height: VIEW_H },
    deviceScaleFactor: 1,
    colorScheme: 'dark',
    reducedMotion: 'reduce',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  });
  await context.addInitScript({ path: DIRECTOR });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e && e.message || e)));
  await page.goto(gameUrl(opts), { waitUntil: 'load' });
  // 注意：rAF 已被接管，waitFor 必须用定时轮询（默认 rAF 轮询会永远等下去）
  await page.waitForFunction(
    () => !!(window.__game && window.__game.renderer && window.__game.world && window.__game.ui && window.__pump),
    null,
    { polling: 50, timeout: 20000 },
  );
  // ?seed= 会在 boot 里重建世界（time 回到 startTod），所以开局时刻在这里才钉得住
  if (typeof opts.tod === 'number') {
    await page.evaluate((t) => {
      const g = window.__game;
      g.world.time = t * window.World.cycleSeconds();
      window.Sim.step(g.world, 0);
    }, opts.tod);
  }
  return { context, page, pageErrors };
}

/** 推进到第 frame 帧并保证合成器提交出来（frame 从 0 起，需逐帧调用才能保持 dt=1/30） */
export async function pumpTo(page, frame, cam) {
  await page.evaluate(
    ([f, c]) => { window.__pump(f, c); return window.__tickReal(); },
    [frame, cam || null],
  );
}

/** 相机固定时一次推进多帧（页内循环，省往返） */
export async function pumpRangeFixed(page, from, to, cam) {
  await page.evaluate(
    ([a, b, c]) => {
      for (let f = a; f <= b; f++) window.__pump(f, c || null);
      return window.__tickReal();
    },
    [from, to, cam || null],
  );
}

/*
 * 预热帧数：世界生成时每栋初始建筑 anim=0，渲染时按 0.6→1.0 缩放，
 * 约 10 帧（0.33 s）才长到完整大小。用负帧号先空跑一段，
 * 起始帧 0 就是「已经稳定的村子」，同时 dt 序列依旧严格 1/30。
 */
export const WARMUP_FRAMES = 12;

export async function warmup(page, cam) {
  await page.evaluate(
    ([n, c]) => {
      for (let i = -n; i <= -1; i++) window.__pump(i, c || null);
      return window.__tickReal();
    },
    [WARMUP_FRAMES, cam || null],
  );
}

/** 相机锚点插值：锚点之间用 smoothstep（两端速度为 0，绝无抖动） */
export function camAt(anchors, frame) {
  if (frame <= anchors[0].f) {
    const a = anchors[0];
    return [a.cx, a.cy, a.z];
  }
  const last = anchors[anchors.length - 1];
  if (frame >= last.f) return [last.cx, last.cy, last.z];
  for (let i = 0; i < anchors.length - 1; i++) {
    const a = anchors[i];
    const b = anchors[i + 1];
    if (frame >= a.f && frame <= b.f) {
      const t = (frame - a.f) / (b.f - a.f);
      const s = t * t * (3 - 2 * t); // smoothstep
      return [a.cx + (b.cx - a.cx) * s, a.cy + (b.cy - a.cy) * s, a.z + (b.z - a.z) * s];
    }
  }
  return [last.cx, last.cy, last.z];
}

/** 与 renderer.worldToScreen 同一套公式：地块浮点坐标 → CSS 像素 */
export function tileToScreen(wx, wy, cam) {
  const [cx, cy, z] = cam;
  return {
    x: VIEW_W / 2 + ((wx - wy) - (cx - cy)) * HW * z,
    y: VIEW_H / 2 + ((wx + wy) - (cx + cy)) * HH * z,
  };
}

/** 地块 (x,y) 中心 → CSS 像素 */
export function tileCenter(x, y, cam) {
  return tileToScreen(x + 0.5, y + 0.5, cam);
}

export function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
  return p;
}

export function frameName(i) {
  return 'f' + String(i).padStart(4, '0') + '.png';
}

export function dirSize(dir) {
  let bytes = 0;
  let n = 0;
  for (const f of fs.readdirSync(dir)) {
    const st = fs.statSync(path.join(dir, f));
    if (st.isFile()) { bytes += st.size; n++; }
  }
  return { bytes, n };
}

export function human(bytes) {
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 100 ? 0 : 1) + ' ' + u[i];
}
