/*
 * 确定性比对：同一批帧在两次独立渲染里的结果。
 *
 *   node scripts/demo-video/game/compare.mjs DIR_A DIR_B --frames=31,181,361
 *
 * 先做逐字节比对（最强证据）。若不完全相同，再用 Chromium 把两张 PNG 解成像素，
 * 统计「不同像素数 / 最大通道差 / 平均通道差 / 差异包围盒」，把差异量化出来。
 */
import fs from 'node:fs';
import path from 'node:path';
import { launch, frameName } from './lib.mjs';

const argv = process.argv.slice(2);
function arg(name, def) {
  const hit = argv.find((a) => a === '--' + name || a.startsWith('--' + name + '='));
  if (!hit) return def;
  const i = hit.indexOf('=');
  return i < 0 ? true : hit.slice(i + 1);
}
const dirA = argv[0];
const dirB = argv[1];
if (!dirA || !dirB) { console.error('用法: compare.mjs DIR_A DIR_B --frames=31,181,361'); process.exit(2); }
const frames = String(arg('frames', '31,181,361')).split(',').map((n) => parseInt(n, 10));

const browser = await launch();
const page = await browser.newPage();

const report = [];
let allIdentical = true;

for (const f of frames) {
  const a = path.join(dirA, frameName(f));
  const b = path.join(dirB, frameName(f));
  const row = { frame: f, name: frameName(f), bytes: null, identical: false, note: '' };
  if (!fs.existsSync(a) || !fs.existsSync(b)) {
    row.note = '缺文件: ' + (!fs.existsSync(a) ? a : b);
    allIdentical = false;
    report.push(row);
    continue;
  }
  const ba = fs.readFileSync(a);
  const bb = fs.readFileSync(b);
  row.bytes = ba.length;
  row.identical = ba.length === bb.length && ba.equals(bb);
  if (row.identical) {
    row.note = '逐字节相同';
  } else {
    allIdentical = false;
    // 量化差异
    const diff = await page.evaluate(async ([da, db]) => {
      async function load(b64) {
        const img = new Image();
        img.src = 'data:image/png;base64,' + b64;
        await img.decode();
        const c = document.createElement('canvas');
        c.width = img.width; c.height = img.height;
        const g = c.getContext('2d', { willReadFrequently: true });
        g.drawImage(img, 0, 0);
        return { w: img.width, h: img.height, d: g.getImageData(0, 0, img.width, img.height).data };
      }
      const A = await load(da);
      const B = await load(db);
      if (A.w !== B.w || A.h !== B.h) return { sizeMismatch: A.w + 'x' + A.h + ' vs ' + B.w + 'x' + B.h };
      let n = 0, maxDelta = 0, sum = 0;
      let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
      for (let i = 0, p = 0; i < A.d.length; i += 4, p++) {
        const dr = Math.abs(A.d[i] - B.d[i]);
        const dg = Math.abs(A.d[i + 1] - B.d[i + 1]);
        const db2 = Math.abs(A.d[i + 2] - B.d[i + 2]);
        const dm = Math.max(dr, dg, db2);
        if (dm > 0) {
          n++;
          sum += (dr + dg + db2) / 3;
          if (dm > maxDelta) maxDelta = dm;
          const x = p % A.w, y = (p / A.w) | 0;
          if (x < x0) x0 = x; if (x > x1) x1 = x;
          if (y < y0) y0 = y; if (y > y1) y1 = y;
        }
      }
      return {
        w: A.w, h: A.h, total: A.w * A.h,
        differing: n, pct: (n / (A.w * A.h)) * 100,
        maxDelta, meanDelta: n ? sum / n : 0,
        bbox: n ? [x0, y0, x1, y1] : null,
      };
    }, [ba.toString('base64'), bb.toString('base64')]);
    row.detail = diff;
    row.note = diff.sizeMismatch
      ? '尺寸不同 ' + diff.sizeMismatch
      : `${diff.differing}/${diff.total} 像素不同 (${diff.pct.toFixed(4)}%) · 最大通道差 ${diff.maxDelta} · 平均 ${diff.meanDelta.toFixed(3)} · 包围盒 ${JSON.stringify(diff.bbox)}`;
  }
  report.push(row);
}

await browser.close();

console.log(`\nA = ${dirA}\nB = ${dirB}\n`);
for (const r of report) {
  console.log(`${r.identical ? '相同' : '不同'}  ${r.name}  ${r.bytes ? r.bytes + ' B' : ''}  ${r.note}`);
}
console.log(`\n结论：${allIdentical ? '两轮渲染在全部抽样帧上逐字节完全相同。' : '存在差异（见上）。'}`);
process.exit(allIdentical ? 0 : 1);
