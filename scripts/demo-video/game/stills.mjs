/*
 * 选种子 / 定构图用的静帧浏览器。
 *
 *   node scripts/demo-video/game/stills.mjs --seeds=99,7,555 --zoom=1.35 --tod=0.35
 *   node scripts/demo-video/game/stills.mjs --seeds=99 --map
 *
 * 对每个种子：开一局干净游戏，把相机钉在村庄上，推进到指定帧，落一张 PNG/JPEG，
 * 并在 stdout 打印村庄中心、资源、可建地块等事实（用于排构图）。
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  launch, openGame, pumpRangeFixed, warmup, ensureDir, OUT_ROOT,
} from './lib.mjs';

const argv = process.argv.slice(2);
function arg(name, def) {
  const hit = argv.find((a) => a === '--' + name || a.startsWith('--' + name + '='));
  if (!hit) return def;
  const i = hit.indexOf('=');
  return i < 0 ? true : hit.slice(i + 1);
}

const seeds = String(arg('seeds', '99')).split(',').map((s) => parseInt(s, 10));
const zoom = parseFloat(arg('zoom', '1.35'));
const tod = parseFloat(arg('tod', '0.35'));
const dy = parseFloat(arg('dy', '1.0'));
const dx = parseFloat(arg('dx', '0.5'));
const frame = parseInt(arg('frame', '90'), 10);
const showMap = !!arg('map', false);
const outDir = ensureDir(String(arg('out', path.join(OUT_ROOT, 'probe'))));

const browser = await launch();
const summary = [];

for (const seed of seeds) {
  const { context, page, pageErrors } = await openGame(browser, { seed, tod });
  const ground = await page.evaluate(() => {
    const g = window.__game;
    const w = g.world;
    const vc = w.village || { x: 12, y: 12 };
    let water = 0, sand = 0, grass = 0, trees = 0, rocks = 0, gold = 0, roads = 0;
    const blds = {};
    for (const t of w.tiles) {
      if (t.terrain === 'water') water++;
      else if (t.terrain === 'sand') sand++;
      else grass++;
      if (t.tree) trees++;
      if (t.rock) (t.rock.kind === 'gold' ? gold++ : rocks++);
      if (t.bld) {
        blds[t.bld.type] = (blds[t.bld.type] || 0) + 1;
        if (t.bld.type === 'road') roads++;
      }
    }
    return {
      vc, seed: w.seed, res: w.res, pop: w.pop, popCap: w.popCap,
      popTxt: (w.pop && typeof w.pop === 'object') ? (w.pop.cur + '/' + w.pop.cap) : String(w.pop),
      terrain: { water, sand, grass }, trees, rocks, gold, roads, blds,
      clockOk: window.__clockOk(),
      vnow: performance.now(),
      canvas: { w: g.renderer.vw, h: g.renderer.vh, dpr: g.renderer.dpr },
      errors: window.__errors.slice(),
    };
  });

  const cam = [ground.vc.x + dx, ground.vc.y + dy, zoom];
  await warmup(page, cam);
  await pumpRangeFixed(page, 0, frame, cam);
  const meta = await page.evaluate(() => {
    const g = window.__game;
    return {
      time: g.world.time, tod: g.world.tod, phase: g.world.phase, day: g.world.day,
      palive: !!window.__game.renderer._order, errors: window.__errors.slice(),
      gameSpeed: g.speed,
    };
  });

  const png = path.join(outDir, `seed-${seed}.png`);
  const jpg = path.join(outDir, `seed-${seed}.jpg`);
  await page.screenshot({ path: png, type: 'png' });
  await page.screenshot({ path: jpg, type: 'jpeg', quality: 88 });

  let mapTxt = '';
  if (showMap) {
    mapTxt = await page.evaluate(() => {
      const w = window.__game.world;
      const rows = [];
      for (let y = 0; y < w.h; y++) {
        let s = '';
        for (let x = 0; x < w.w; x++) {
          const t = w.tiles[y * w.w + x];
          let c;
          if (t.bld) c = t.bld.type === 'road' ? '+' : (t.bld.type === 'house' ? 'H' : t.bld.type[0].toUpperCase());
          else if (t.tree) c = 'T';
          else if (t.rock) c = t.rock.kind === 'gold' ? 'G' : 'R';
          else if (t.terrain === 'water') c = '~';
          else if (t.terrain === 'sand') c = '.';
          else c = ' ';
          s += c;
        }
        rows.push(String(y).padStart(2, ' ') + '|' + s);
      }
      return rows.join('\n');
    });
  }

  summary.push({ seed, ground, meta, png });
  console.log(`\n=== seed ${seed} ===`);
  console.log('  village center :', ground.vc.x + ',' + ground.vc.y, ' world seed', ground.seed);
  console.log('  camera         :', cam.map((n) => n.toFixed(2)).join(', '));
  console.log('  canvas         :', ground.canvas.w + 'x' + ground.canvas.h, 'dpr', ground.canvas.dpr);
  console.log('  clock virtual  :', ground.clockOk, '(performance.now =', ground.vnow + ')');
  console.log('  terrain        :', JSON.stringify(ground.terrain), ' trees', ground.trees, ' rock', ground.rocks, ' gold', ground.gold);
  console.log('  buildings      :', JSON.stringify(ground.blds), ' roads', ground.roads);
  console.log('  resources      :', JSON.stringify(ground.res), ' pop', ground.popTxt);
  console.log('  after pumps    : time', meta.time.toFixed(2), 'tod', meta.tod.toFixed(3), meta.phase, 'day', meta.day);
  console.log('  errors         :', JSON.stringify((meta.errors || []).concat(pageErrors || [])));
  console.log('  ->', png);
  if (mapTxt) console.log('\n' + mapTxt + '\n');
  await context.close();
}

await browser.close();
console.log('\n' + outDir);
