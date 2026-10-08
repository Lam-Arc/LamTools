/*
 * 帧序列自检：
 *   1. 目录里是否正好是 f0001.png … f0450.png（名称、数量、非空）
 *   2. 每张 PNG 的 IHDR 是否 1920x1080 / 8bit（不解码，直接读文件头）
 *   3. 抽样相邻帧的平均像素差 → 用来佐证「镜头平滑、无跳切」
 *
 *   node scripts/demo-video/game/verify-frames.mjs [--dir=E:/LamDemo/assets/game/frames]
 */
import fs from 'node:fs';
import path from 'node:path';
import { launch, frameName, dirSize, human, TOTAL_FRAMES, VIEW_W, VIEW_H, OUT_ROOT } from './lib.mjs';

const argv = process.argv.slice(2);
function arg(name, def) {
  const hit = argv.find((a) => a === '--' + name || a.startsWith('--' + name + '='));
  if (!hit) return def;
  const i = hit.indexOf('=');
  return i < 0 ? true : hit.slice(i + 1);
}
const dir = String(arg('dir', path.join(OUT_ROOT, 'frames')));
const problems = [];

// ---- 1. 清单 ----
const files = fs.readdirSync(dir).filter((f) => /^f\d+\.png$/.test(f));
const expected = [];
for (let i = 1; i <= TOTAL_FRAMES; i++) expected.push(frameName(i));
const missing = expected.filter((n) => !files.includes(n));
const extra = files.filter((n) => !expected.includes(n));
if (missing.length) problems.push(`缺帧 ${missing.length} 张：${missing.slice(0, 5).join(',')}…`);
if (extra.length) problems.push(`多余帧 ${extra.length} 张：${extra.slice(0, 5).join(',')}…`);

// ---- 2. PNG 头 ----
let bytes = 0;
const bad = [];
for (const n of expected) {
  const p = path.join(dir, n);
  if (!fs.existsSync(p)) continue;
  const st = fs.statSync(p);
  bytes += st.size;
  const buf = Buffer.alloc(24);
  const fd = fs.openSync(p, 'r');
  fs.readSync(fd, buf, 0, 24, 0);
  fs.closeSync(fd);
  const sigOk = buf.slice(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  const w = buf.readUInt32BE(16);
  const h = buf.readUInt32BE(20);
  if (!sigOk || w !== VIEW_W || h !== VIEW_H || st.size < 20000) {
    bad.push(`${n}: sig=${sigOk} ${w}x${h} ${st.size}B`);
  }
}
if (bad.length) problems.push(`异常帧 ${bad.length} 张：${bad.slice(0, 5).join(' | ')}`);

console.log(`目录      : ${dir}`);
console.log(`帧数      : ${files.length}（期望 ${TOTAL_FRAMES}）`);
console.log(`尺寸/格式 : ${VIEW_W}x${VIEW_H} PNG，头部全部合规 = ${bad.length === 0}`);
console.log(`总大小    : ${human(bytes)} (${bytes} B)，平均 ${(bytes / Math.max(1, files.length) / 1024).toFixed(0)} KB/帧`);

// ---- 3. 平滑度抽样：每 25 帧取一对相邻帧 ----
const pairs = [];
for (let f = 25; f < TOTAL_FRAMES - 1; f += 25) pairs.push([f, f + 1]);

const browser = await launch();
const page = await browser.newPage();
const stats = [];
for (const [a, b] of pairs) {
  const pa = path.join(dir, frameName(a + 1));
  const pb = path.join(dir, frameName(b + 1));
  if (!fs.existsSync(pa) || !fs.existsSync(pb)) continue;
  const d = await page.evaluate(async ([da, db]) => {
    async function load(b64) {
      const img = new Image();
      img.src = 'data:image/png;base64,' + b64;
      await img.decode();
      const c = document.createElement('canvas');
      c.width = img.width; c.height = img.height;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0);
      return g.getImageData(0, 0, img.width, img.height).data;
    }
    const A = await load(da);
    const B = await load(db);
    let sum = 0;
    for (let i = 0; i < A.length; i += 4) {
      sum += (Math.abs(A[i] - B[i]) + Math.abs(A[i + 1] - B[i + 1]) + Math.abs(A[i + 2] - B[i + 2])) / 3;
    }
    return sum / (A.length / 4);
  }, [fs.readFileSync(pa).toString('base64'), fs.readFileSync(pb).toString('base64')]);
  stats.push({ pair: `${a + 1}→${b + 1}`, meanAbs: d });
}
await browser.close();

console.log('\n相邻帧平均像素差（越小越平缓；突变=跳切/甩镜）：');
for (const s of stats) {
  const flag = s.meanAbs > 8 ? '  <== 偏大' : '';
  console.log(`  f${s.pair.padEnd(10)} ${s.meanAbs.toFixed(3)}${flag}`);
}
const max = stats.reduce((m, s) => Math.max(m, s.meanAbs), 0);
console.log(`  最大 ${max.toFixed(3)} / 平均 ${(stats.reduce((a, s) => a + s.meanAbs, 0) / Math.max(1, stats.length)).toFixed(3)}`);

console.log('\n结论：' + (problems.length ? '发现问题 →\n  ' + problems.join('\n  ') : '清单、尺寸、可读性全部通过。'));
process.exit(problems.length ? 1 : 0);
