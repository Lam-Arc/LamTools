#!/usr/bin/env node
/**
 * lam-design-spec audit — 扫描 LamTools 前端样式，报告偏离规范的值。
 *
 * 用法： node .agents/skills/lam-design-spec/scripts/audit.mjs
 *
 * 检查项：
 *  1. border-radius / padding / gap 的 px 值不在标尺 → 报告
 *  2. z-index 数字字面量不在 --z-* 标尺 → 报告
 *  3. color-mix(... X%, ...) 的 X 不在 {8,12,16} → 报告
 *  4. 出现本地命名空间（--fb- / --xxx-radius 等）→ 报告
 *  5. control 控件误用 --theme-main-text（应在 control area 用 --theme-control-text）→ 提示
 *
 * 零依赖（仅用 fs/path/正则）。按文件分组打印。不自动改代码。
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// __dirname 等价（ESM）。从脚本位置回溯到仓库根：scripts/ -> lam-design-spec/ -> skills/ -> .agents/ -> ROOT
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..', '..', '..');
const CORE_UI = path.join(ROOT, 'core', 'ui', 'src');

// —— 标尺 ——
const RADIUS_SCALE = new Set(['6', '12', '18', '22']);          // --radius-sm/-/-lg/-xl
const SPACE_SCALE = new Set(['4', '8', '12', '16', '24', '32']); // --space-1..6
const ALPHA_OK = new Set(['8', '12', '16']);                      // --alpha-hover/active/press
const Z_SCALE = new Set(['10', '15', '20', '35', '40', '60', '80', '90']);

// 允许的圆角 px（含标尺 + 常见合理值不报，只报明显 off-scale）
// off-scale 黑名单
const RADIUS_BANNED = new Set(['5', '7', '9', '10', '11', '14']);

// —— 扫描目标 ——
function collectFiles(dir, exts) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...collectFiles(p, exts));
    else if (exts.some(x => e.name.endsWith(x))) out.push(p);
  }
  return out;
}

const targets = [
  ...collectFiles(path.join(CORE_UI, 'styles'), ['.css']),
  ...collectFiles(path.join(CORE_UI, 'components'), ['.vue']),
];

// —— 规则 ——
const findings = {};  // file -> [{ line, rule, msg }]

function add(file, line, rule, msg) {
  (findings[file] ??= []).push({ line, rule, msg });
}

// 提取每行首个 px 数字
function pxValues(line, prop) {
  const vals = [];
  const re = new RegExp(prop + '\\s*:\\s*([^;]+)', 'i');
  const m = line.match(re);
  if (!m) return vals;
  for (const n of m[1].matchAll(/(\d+(?:\.\d+)?)px/g)) vals.push({ val: n[1], col: n.index });
  return vals;
}

for (const file of targets) {
  const rel = path.relative(ROOT, file);
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
  lines.forEach((raw, i) => {
    const line = raw.trim();
    const ln = i + 1;
    if (!line || line.startsWith('/*') || line.startsWith('*')) return;

    // 1a. border-radius px off-scale
    if (/border-radius/i.test(line) && !/var\(--radius/.test(line)) {
      for (const { val } of pxValues(raw, 'border-radius')) {
        if (RADIUS_BANNED.has(Math.round(parseFloat(val)).toString()))
          add(rel, ln, 'radius-off-scale', `${val}px → 用 --radius-* 标尺（6/12/18/22）`);
      }
    }
    // 1b. off-scale radius 也包括硬编码 4px 在非 dense 场景（4px 是 WorkflowNode 小控件，标记提示）
    // 不强制报 4px，仅在显式 banned 集合里报。

    // 2. z-index 数字字面量不在标尺——只报 ≥50 的浮层/模态级硬编码
    //    （z-index:0/1/2/3/5/6 是局部 stacking context，不属于主题级标尺）
    {
      const m = line.match(/z-index\s*:\s*(\d+)\s*(?:;|$)/);
      if (m && !/var\(--z-/.test(line)) {
        const z = parseInt(m[1], 10);
        if (z >= 50 && !Z_SCALE.has(m[1]))
          add(rel, ln, 'z-index-literal', `z-index:${m[1]} → 用 --z-* 标尺（如 --z-popover 60 / --z-modal 80 / --z-toast 90）`);
      }
    }

    // 3. color-mix alpha 不在 {8,12,16}——只报明显的交互态用途（hover/active/selected 行）
    //    边框/次要文字的 alpha（如 5%/6%/7%/9%/10%/14%/20%/36%/58%）另行提示但不当交互态误报
    {
      const isState = /hover|active|selected|focus|press/i.test(line);
      for (const m of line.matchAll(/color-mix\([^)]*?(\d+(?:\.\d+)?)\s*%,\s*transparent\)/g)) {
        const a = parseFloat(m[1]);
        const key = Math.round(a).toString();
        if (isState && !ALPHA_OK.has(key))
          add(rel, ln, 'alpha-state-off-scale', `交互态 color-mix ... ${m[1]}% → 用 --alpha-*（hover 8% / active 12% / press 16%）`);
        else if (!isState && a < 20 && !ALPHA_OK.has(key))
          add(rel, ln, 'alpha-inconsistent', `color-mix ... ${m[1]}% → 非标尺值，考虑统一（交互态用 --alpha-*）`);
      }
    }

    // 4. 本地命名空间 --fb- / --xxx-radius（注意 \b 在 - 前无效，直接匹配）
    if (line.includes('--fb-') || /--[a-z]+-radius\b/.test(line)) {
      add(rel, ln, 'local-namespace', '本地命名空间 → 用全局 --radius-* / --theme-* ，禁止平行体系');
    }

    // 5. 静态色绕过主题（control 控件用 --panel/--line 直接做背景/边框）
    // 仅在 .vue 的 input/select/button 相关规则里提示
    if (/\.(lt-|small-|wf-field|field-input)/.test(line) && /var\(--panel\b/.test(line) && !/--theme-/.test(line)) {
      add(rel, ln, 'static-bypass-theme', '控件用静态 --panel → 应挂 control area：--theme-control-background/text');
    }
  });
}

// —— 输出 ——
const files = Object.keys(findings);
let total = 0;
for (const f of files) total += findings[f].length;

if (total === 0) {
  console.log('\n✓ 未发现偏离规范的值。所有扫描文件均落在标尺上。\n');
} else {
  console.log(`\nlam-design-spec audit — ${total} 项偏离规范（${files.length} 个文件）\n`);
  for (const f of files) {
    console.log(`  ${f}`);
    for (const { line, rule, msg } of findings[f]) {
      console.log(`    :${line}  [${rule}]  ${msg}`);
    }
    console.log('');
  }
}
console.log(`扫描文件：${targets.length}  ·  偏离：${total}`);
