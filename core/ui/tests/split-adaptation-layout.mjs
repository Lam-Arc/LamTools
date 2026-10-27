// user:“专门对小屏或者说分屏状态做一下适配”+(用真实排版引擎校验宽窗口中的不同窗格宽度，不操作桌面应用)。
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'

const browser = process.env.LAMTOOLS_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const directory = mkdtempSync(join(tmpdir(), 'lam-split-layout-'))
try {
  const css = ['variables.css', 'layout.css', 'library-surface.css', 'app-page.css']
    .map(name => readFileSync(resolve('src/styles', name), 'utf8')).join('\n')
  const fixture = join(directory, 'layout.html')
  writeFileSync(fixture, `<!doctype html><meta charset="utf-8"><style>${css}
    body { width: 1400px; margin: 0; }
    .core-app-page { height: 500px; }
    .plan-grid { display:grid; }
    .install-input { min-width:220px; }
  </style><div class="core-app-page"><div class="full-area-view">
    <div class="settings-page"><aside class="settings-sidebar"><nav class="settings-nav">
    ${Array.from({length:12}, (_, i) => `<button>设置分区 ${i}</button>`).join('')}
    </nav></aside><main class="settings-main"><input class="install-input"></main></div>
  </div></div><div class="core-app-page"><div class="library-surface"><div class="plan-grid"><div>方案 A</div><div>方案 B</div></div></div></div>
  <script>
    const results = [];
    const pages = document.querySelectorAll('.core-app-page');
    for (const width of [1000, 620, 360, 260]) {
      pages.forEach(page => page.style.width = width + 'px');
      const nav = document.querySelector('.settings-nav');
      const main = document.querySelector('.settings-main');
      const input = document.querySelector('.install-input');
      results.push({width, layout: getComputedStyle(document.querySelector('.settings-page')).display,
        navDisplay: getComputedStyle(nav).display, navOverflow: getComputedStyle(nav).overflowX,
        navFits: nav.clientWidth <= width, inputFits: input.getBoundingClientRect().width <= main.clientWidth,
        columns: getComputedStyle(document.querySelector('.plan-grid')).gridTemplateColumns.split(' ').length});
    }
    document.body.innerHTML = '<pre id="result">' + JSON.stringify({viewport: innerWidth, results}) + '</pre>';
  </script>`)
  const output = execFileSync(browser, ['--headless', '--window-size=1400,900', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    `--user-data-dir=${join(directory, 'profile')}`, '--dump-dom', pathToFileURL(fixture).href],
    { encoding: 'utf8', timeout: 45000, stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true })
  const report = JSON.parse(output.match(/<pre id="result">(.*?)<\/pre>/s)?.[1] || 'null')
  assert.ok(report, 'Browser must finish the layout checks')
  assert.ok(report.viewport >= 1300, 'Use a wide desktop viewport for narrow-pane verification')
  const results = report.results
  assert.equal(results[0].layout, 'grid')
  for (const result of results.slice(1)) {
    assert.equal(result.layout, 'flex', `navigation folds at ${result.width}px`)
    assert.equal(result.navDisplay, 'flex')
    assert.equal(result.navOverflow, 'auto')
    assert.ok(result.navFits, `navigation stays inside ${result.width}px`)
    assert.ok(result.inputFits, `plugin input stays inside ${result.width}px`)
  }
  for (const result of results.slice(2)) assert.equal(result.columns, 1)
  console.log('PASS: 1400px desktop window; 1000 / 620 / 360 / 260px panes; navigation, plugin fields, library grid.')
} finally {
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
