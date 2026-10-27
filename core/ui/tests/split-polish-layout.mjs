// user:“样式优化：动画、交互体验、圆角策略等”+(以无界面排版检查统一圆角与减少动画模式，不操作桌面应用)。
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'

const browser = process.env.LAMTOOLS_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const directory = mkdtempSync(join(tmpdir(), 'lam-split-polish-'))
try {
  const css = ['variables.css', 'split-workspace.css'].map(name => readFileSync(resolve('src/styles', name), 'utf8').replace(/^\uFEFF/, '')).join('\n')
  const fixture = join(directory, 'polish.html')
  writeFileSync(fixture, `<!doctype html><meta charset="utf-8"><style>${css}
    .split-workspace { --workspace-panel-radius-inner:18px; --workspace-panel-radius-outer:22px; inset:0; }
  </style><div class="split-workspace split-workspace--open">
    <section class="split-pane-frame"><div class="split-pane-bar"><div class="split-pane-tab">文件</div></div></section>
    <section class="split-tab-content split-tab-content--editor"></section>
    <section class="split-tab-content split-tab-content--browser"></section>
    <div class="split-divider split-divider--columns is-resizing"></div>
  </div><script>
    const style = selector => getComputedStyle(document.querySelector(selector));
    const root = style('.split-workspace'), tab = style('.split-pane-tab');
    document.body.innerHTML = '<pre id="result">' + JSON.stringify({
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      outer: [root.borderTopLeftRadius, root.borderTopRightRadius],
      frame: style('.split-pane-frame').borderTopLeftRadius,
      content: style('.split-tab-content').borderBottomRightRadius,
      tab: tab.borderTopLeftRadius, token:tab.getPropertyValue('--radius-sm'), transition: tab.transitionDuration,
      editorMotion: style('.split-tab-content--editor').animationName,
      browserMotion: style('.split-tab-content--browser').animationName,
      grip: getComputedStyle(document.querySelector('.split-divider'), '::after').opacity
    }) + '</pre>';
  </script>`)
  for (const reduced of [false, true]) {
    const output = execFileSync(browser, ['--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
      ...(reduced ? ['--force-prefers-reduced-motion'] : []), `--user-data-dir=${join(directory, reduced ? 'reduced' : 'normal')}`,
      '--dump-dom', pathToFileURL(fixture).href], { encoding: 'utf8', timeout: 45000, stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true })
    const result = JSON.parse(output.match(/<pre id="result">(.*?)<\/pre>/s)?.[1] || 'null')
    assert.ok(result)
    assert.equal(result.reduced, reduced)
    assert.deepEqual(result.outer, ['18px', '22px'])
    assert.equal(result.frame, '0px'); assert.equal(result.content, '0px'); assert.equal(result.tab, '6px', JSON.stringify(result))
    assert.equal(result.browserMotion, 'none')
    assert.equal(result.editorMotion, reduced ? 'none' : 'split-content-reveal')
    assert.equal(result.transition, reduced ? '0s' : '0.12s, 0.12s')
    assert.equal(result.grip, '1')
  }
  console.log('PASS: shared outer corners, square intersections, small tab corners, resizing grip, normal/reduced motion, native browser exclusion.')
} finally {
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
