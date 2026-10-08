/*
 * 林溪小镇 · 演示视频 · 确定性导演（注入脚本，先于页面任何 js 执行）
 * ---------------------------------------------------------------------
 * 目标：把「真实页面」的渲染循环交给我们自己驱动，使第 N 帧的像素可复现。
 *
 * 做法：
 *   1. 虚拟时钟   —— performance.now / Date.now 全部由 __vnow 提供，页面拿不到真实时间。
 *   2. rAF 接管   —— requestAnimationFrame 只入队，不注册；由 __pump(frame) 一次性 flush。
 *                    游戏主循环 main.js 的 frame(now) 因此按我们给定的 now 推进，
 *                    每帧 dt 恒为 1/30 s（固定步长）。
 *   3. 虚拟定时器 —— setTimeout / setInterval 不再走真实时间，由 __pump 在虚拟时间轴上触发。
 *   4. 种子化随机 —— Math.random 换成 mulberry32 固定序列（游戏只在无 seed 时用它生成地图）。
 *   5. CSS 动画/过渡关死 —— animation / transition 由真实时间驱动，是确定性的头号敌人。
 *
 * 页面不需要做任何修改；本文件不修改 village-game/ 下任何内容。
 */
(() => {
  'use strict';

  const T0 = 1700000000000; // 固定挂钟原点（仅用于 Date.now 之类的旁支数值）
  const STEP_MS = 1000 / 30;

  window.__vnow = 0;
  window.__errors = window.__errors || [];

  // ---- 1. 虚拟时钟 -----------------------------------------------------
  try {
    performance.now = () => window.__vnow;
  } catch (e) { /* 某些实现只读，忽略 */ }
  try {
    Date.now = () => T0 + window.__vnow;
  } catch (e) { /* 忽略 */ }

  // ---- 4. 种子化 Math.random ------------------------------------------
  let rs = 0x9e3779b9 >>> 0;
  Math.random = () => {
    rs = (rs + 0x6d2b79f5) >>> 0;
    let t = rs;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  // ---- 2. rAF 手动队列 -------------------------------------------------
  // 保留真实 rAF：截图前用它要一帧，确保合成器把 canvas 的最新位图提交出来。
  const realRaf = typeof window.requestAnimationFrame === 'function'
    ? window.requestAnimationFrame.bind(window)
    : (cb) => realSetTimeout(() => cb(window.__vnow), 16);
  window.__tickReal = () => new Promise((res) => realRaf(() => res(1)));

  const rafQ = [];
  let rafSeq = 1;
  window.requestAnimationFrame = (cb) => {
    const id = rafSeq++;
    if (typeof cb === 'function') rafQ.push({ id, cb });
    return id;
  };
  window.cancelAnimationFrame = (id) => {
    const i = rafQ.findIndex((e) => e.id === id);
    if (i >= 0) rafQ.splice(i, 1);
  };

  // ---- 3. 虚拟定时器 ---------------------------------------------------
  const timers = [];
  let tSeq = 1;
  const realSetTimeout = window.setTimeout.bind(window);
  window.setTimeout = (fn, ms, ...a) => {
    const id = tSeq++;
    timers.push({ id, at: window.__vnow + (+ms || 0), fn, a, every: 0 });
    return id;
  };
  window.setInterval = (fn, ms, ...a) => {
    const id = tSeq++;
    const p = Math.max(1, +ms || 1);
    timers.push({ id, at: window.__vnow + p, fn, a, every: p });
    return id;
  };
  const killTimer = (id) => {
    const i = timers.findIndex((t) => t.id === id);
    if (i >= 0) timers.splice(i, 1);
  };
  window.clearTimeout = killTimer;
  window.clearInterval = killTimer;

  // ---- 5. 关死 CSS 动画与过渡 -----------------------------------------
  (function freezeCss() {
    const css = '*,*::before,*::after{animation:none !important;transition:none !important}' +
      'html{overflow:hidden !important}' +
      '#game-canvas{cursor:none !important}';
    const st = document.createElement('style');
    st.setAttribute('data-determinism', '1');
    st.textContent = css;
    const host = document.head || document.documentElement;
    if (host) host.appendChild(st);
    else document.addEventListener('readystatechange', function once() {
      (document.head || document.documentElement).appendChild(st);
      document.removeEventListener('readystatechange', once);
    });
  })();

  function fireTimers() {
    for (let guard = 0; guard < 5000; guard++) {
      let idx = -1;
      let best = Infinity;
      for (let i = 0; i < timers.length; i++) {
        const t = timers[i];
        if (t.at <= window.__vnow && t.at < best) { best = t.at; idx = i; }
      }
      if (idx < 0) return;
      const t = timers[idx];
      if (t.every) t.at = window.__vnow + t.every;
      else timers.splice(idx, 1);
      try { t.fn.apply(null, t.a || []); } catch (e) { window.__errors.push('timer: ' + e); }
    }
  }

  /**
   * 推进到第 frameIndex 帧（0 起）。
   * cam = [cx, cy, zoom]（可选）：在画之前把相机钉到时间表上的位置。
   * 返回本帧结束后待运行的 rAF 回调数（1 表示主循环还活着）。
   */
  window.__pump = function (frameIndex, cam) {
    window.__vnow = frameIndex * STEP_MS;
    const g = window.__game;
    if (g && cam) {
      g.camera.cx = cam[0];
      g.camera.cy = cam[1];
      g.camera.zoom = cam[2];
    }
    fireTimers();
    const batch = rafQ.splice(0, rafQ.length);
    for (let i = 0; i < batch.length; i++) {
      try { batch[i].cb(window.__vnow); } catch (e) { window.__errors.push('raf: ' + (e && e.stack || e)); }
    }
    return rafQ.length;
  };

  // 确定性自检：虚拟时钟是否真的接管了（供渲染脚本断言用）
  window.__clockOk = function () {
    return performance.now() === window.__vnow && Date.now() === T0 + window.__vnow;
  };
})();
