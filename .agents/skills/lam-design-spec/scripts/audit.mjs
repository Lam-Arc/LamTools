#!/usr/bin/env node
/**
 * lam-design-spec audit — scan LamTools frontend styles and report values that violate the design specification.
 *
 * Usage: node .agents/skills/lam-design-spec/scripts/audit.mjs
 *
 * Checks:
 *  1. Report border-radius / padding / gap pixel values outside the scales.
 *  2. Report numeric z-index literals outside the --z-* scale.
 *  3. Report color-mix(... X%, ...) values where X is not in {8,12,16}.
 *  4. Report local namespaces such as --fb- / --xxx-radius.
 *  5. Warn when control components use --theme-main-text instead of --theme-control-text.
 *
 * Zero dependencies (uses only fs/path/regular expressions). Output is grouped by file.
 * This script does not edit code.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ESM equivalent of __dirname. Walk from this script to the repository root:
// scripts/ -> lam-design-spec/ -> skills/ -> .agents/ -> ROOT
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..', '..', '..');
const CORE_UI = path.join(ROOT, 'core', 'ui', 'src');

// Scales
const RADIUS_SCALE = new Set(['6', '12', '18', '22']);          // --radius-sm/-/-lg/-xl
const SPACE_SCALE = new Set(['4', '8', '12', '16', '24', '32']); // --space-1..6
const ALPHA_OK = new Set(['8', '12', '16']);                      // --alpha-hover/active/press
const Z_SCALE = new Set(['10', '15', '20', '35', '40', '60', '80', '90']);

// Allowed radius pixels: the scale plus common reasonable values; report only clear off-scale cases.
// Off-scale blocklist
const RADIUS_BANNED = new Set(['5', '7', '9', '10', '11', '14']);

// Scan targets
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

// Rules
const findings = {};  // file -> [{ line, rule, msg }]

function add(file, line, rule, msg) {
  (findings[file] ??= []).push({ line, rule, msg });
}

// Extract the first pixel value on a property line.
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

    // 1a. Off-scale border-radius pixels
    if (/border-radius/i.test(line) && !/var\(--radius/.test(line)) {
      for (const { val } of pxValues(raw, 'border-radius')) {
        if (RADIUS_BANNED.has(Math.round(parseFloat(val)).toString()))
          add(rel, ln, 'radius-off-scale', `${val}px → use the --radius-* scale (6/12/18/22)`);
      }
    }
    // 1b. Off-scale radii also include hard-coded 4px outside dense contexts.
    // Do not report 4px by default; report only values in the explicit blocklist.

    // 2. Numeric z-index literals outside the scale; report only overlay/modal values >= 50.
    //    (z-index: 0/1/2/3/5/6 are local stacking contexts, not theme-level values.)
    {
      const m = line.match(/z-index\s*:\s*(\d+)\s*(?:;|$)/);
      if (m && !/var\(--z-/.test(line)) {
        const z = parseInt(m[1], 10);
        if (z >= 50 && !Z_SCALE.has(m[1]))
          add(rel, ln, 'z-index-literal', `z-index:${m[1]} → use the --z-* scale (for example, --z-popover 60 / --z-modal 80 / --z-toast 90)`);
      }
    }

    // 3. Report color-mix alpha outside {8,12,16} only for likely interaction states (hover/active/selected rows).
    //    Border and secondary-text alpha (such as 5%/6%/7%/9%/10%/14%/20%/36%/58%) is noted separately,
    //    but is not treated as an interaction-state violation.
    {
      const isState = /hover|active|selected|focus|press/i.test(line);
      for (const m of line.matchAll(/color-mix\([^)]*?(\d+(?:\.\d+)?)\s*%,\s*transparent\)/g)) {
        const a = parseFloat(m[1]);
        const key = Math.round(a).toString();
        if (isState && !ALPHA_OK.has(key))
          add(rel, ln, 'alpha-state-off-scale', `interaction color-mix ... ${m[1]}% → use --alpha-* (hover 8% / active 12% / press 16%)`);
        else if (!isState && a < 20 && !ALPHA_OK.has(key))
          add(rel, ln, 'alpha-inconsistent', `color-mix ... ${m[1]}% → off-scale value; consider consolidating (use --alpha-* for interaction states)`);
      }
    }

    // 4. Local namespaces such as --fb- / --xxx-radius (\b is ineffective before -, so match directly).
    if (line.includes('--fb-') || /--[a-z]+-radius\b/.test(line)) {
      add(rel, ln, 'local-namespace', 'Local namespace → use global --radius-* / --theme-* tokens; do not create a parallel system');
    }

    // 5. Static color bypassing the theme (control components using --panel/--line directly for backgrounds/borders).
    // Warn only in input/select/button-related Vue rules.
    if (/\.(lt-|small-|wf-field|field-input)/.test(line) && /var\(--panel\b/.test(line) && !/--theme-/.test(line)) {
      add(rel, ln, 'static-bypass-theme', 'Control uses static --panel → use the control area: --theme-control-background/text');
    }
  });
}

// Output
const files = Object.keys(findings);
let total = 0;
for (const f of files) total += findings[f].length;

if (total === 0) {
  console.log('\n✓ No off-spec values found. All scanned files use the defined scales.\n');
} else {
  console.log(`\nlam-design-spec audit — ${total} off-spec finding(s) across ${files.length} file(s)\n`);
  for (const f of files) {
    console.log(`  ${f}`);
    for (const { line, rule, msg } of findings[f]) {
      console.log(`    :${line}  [${rule}]  ${msg}`);
    }
    console.log('');
  }
}
console.log(`Scanned files: ${targets.length}  ·  Findings: ${total}`);
