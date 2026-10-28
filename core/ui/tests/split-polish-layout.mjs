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
    :root { --theme-main-background:#1b1d22; --theme-main-text:#fbf7f0; --theme-control-text:#2e3138; --theme-control-soft-background:rgba(255,255,252,.82); }
    .split-workspace { --workspace-panel-radius-inner:18px; --workspace-panel-radius-outer:22px; inset:0; }
  </style><div class="split-workspace split-workspace--open">
    <section class="split-pane-frame" style="left:0;top:0;width:640px;height:220px">
      <div class="split-pane-bar is-active">
        <div class="split-pane-tabs">
          <div class="split-pane-tab is-selected"><button role="tab">文件</button><button class="split-tab-close" aria-label="关闭">×</button></div>
          <div class="split-pane-tab"><button role="tab">另一个窗口</button><button class="split-tab-close" aria-label="关闭">×</button></div>
        </div>
        <button class="split-icon-button" aria-label="打开内容">+</button>
        <button class="split-icon-button split-pane-close" aria-label="关闭分屏">×</button>
        <span class="split-corner-grip split-corner-grip--top-left"></span>
      </div>
    </section>
    <section class="split-tab-content split-tab-content--editor"></section>
    <section class="split-tab-content split-tab-content--browser"></section>
    <div class="split-divider split-divider--columns is-resizing"></div>
    <div class="split-corner-grip split-corner-grip--bottom-left" style="left:0;top:20px;width:18px;height:18px;bottom:auto"></div>
  </div><script>
    const style = selector => getComputedStyle(document.querySelector(selector));
    const root = style('.split-workspace'), tab = style('.split-pane-tab.is-selected'), other = style('.split-pane-tab:not(.is-selected)');
    const corner = getComputedStyle(document.querySelector('.split-corner-grip--bottom-left'), '::before');
    document.body.innerHTML = '<pre id="result">' + JSON.stringify({
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      outer: [root.borderTopLeftRadius, root.borderTopRightRadius],
      frame: style('.split-pane-frame').borderTopLeftRadius,
      content: style('.split-tab-content').borderBottomRightRadius,
      tab: tab.borderTopLeftRadius, token:tab.getPropertyValue('--radius-sm'), transition: tab.transitionDuration,
      tabHeight: parseFloat(tab.height), tabBg: tab.backgroundColor, tabColor: other.color,
      cornerMask: Boolean((corner.maskImage || corner.webkitMaskImage) && (corner.maskImage || corner.webkitMaskImage) !== 'none'),
      cornerRotation: corner.transform,
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
    assert.equal(result.tabHeight, 28, JSON.stringify(result))
    assert.notEqual(result.tabBg, 'rgba(0, 0, 0, 0)', JSON.stringify(result))
    assert.ok(!result.tabBg.includes('0.82'), JSON.stringify(result))
    assert.match(result.tabBg, /0\.12|12%/, JSON.stringify(result))
    assert.match(result.tabColor, /0\.65|65%/, JSON.stringify(result))
    assert.equal(result.cornerMask, true, JSON.stringify(result))
    assert.notEqual(result.cornerRotation, 'none', JSON.stringify(result))
    assert.equal(result.browserMotion, 'none')
    assert.equal(result.editorMotion, reduced ? 'none' : 'split-content-reveal')
    assert.equal(result.transition, reduced ? '0s' : '0.12s, 0.12s')
    assert.equal(result.grip, '1')
  }
  console.log('PASS: shared outer corners, square intersections, small tab corners, resizing grip, normal/reduced motion, native browser exclusion.')
} finally {
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
