// user:“拉起其他分屏的时候...通过拖动拉起，而不是点击按钮。就类似 blender”+(用真实排版引擎验证手柄拖动预览、落屏和入场动画，不操作桌面应用)。
import { createServer } from 'vite'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import assert from 'node:assert/strict'

const directory = mkdtempSync(join(tmpdir(), 'lam-split-pull-'))
const page = `<!doctype html><meta charset="utf-8"><style>
  :root { --main-left: 0px; --main-right: 0px; --titlebar-offset: 0px; --shell-bottom-inset: 0px; --workspace-panel-radius-inner: 12px; --workspace-panel-radius-outer: 16px; }
  html, body { margin: 0; height: 100%; background: #141414; color: #e6e6e6; }
  #app { height: 100%; }
</style><div id="app"></div><pre id="result">loading</pre><script type="module" src="/__split_pull_entry.js"></script>`
const entry = `
import { createApp, h, nextTick, ref } from 'vue'
import CoreSplitWorkspace from '/src/components/CoreSplitWorkspace.vue'
import { useSplitWorkspace } from '/src/split/useSplitWorkspace'
import '/src/styles/variables.css'; import '/src/styles/base.css'; import '/src/styles/layout.css';

createApp({ setup() {
  const controller = useSplitWorkspace(ref('split-pull-layout'), ref('E:/demo'))
  const pane = controller.split('main', 'right')
  if (pane) controller.add('page', 'settings', '设置', pane)
  return () => h(CoreSplitWorkspace, { controller, workRoot: 'E:/demo' }, {
    default: ({ tab }) => h('div', { style: 'padding:20px;font:14px sans-serif' }, tab.title),
  })
} }).mount('#app')

const frame = () => new Promise(resolve => requestAnimationFrame(() => resolve()))
try {
  await nextTick(); await frame()
  const handle = document.querySelector('.split-split-handle')
  const pane = document.querySelector('.split-pane-frame')
  const handleRect = handle.getBoundingClientRect(), paneRect = pane.getBoundingClientRect()
  const startX = handleRect.left + handleRect.width / 2, startY = handleRect.top + handleRect.height / 2
  handle.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, button: 0, pointerId: 1, clientX: startX, clientY: startY }))
  window.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 1, clientX: startX + 140, clientY: startY }))
  await frame()
  const preview = document.querySelector('.split-pull-preview'), previewRect = preview?.getBoundingClientRect()
  const previewLabel = preview?.textContent?.trim()
  const pulling = document.body.classList.contains('split-is-pulling')
  window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1, clientX: startX + 140, clientY: startY }))
  await nextTick()
  const panes = document.querySelectorAll('.split-pane-frame').length
  const entering = document.querySelectorAll('.split-pane-frame.is-entering').length
  const stillPulling = document.body.classList.contains('split-is-pulling')
  await frame()
  document.querySelector('#result').textContent = JSON.stringify({
    paneWidth: paneRect.width, paneRight: paneRect.right, paneLeft: paneRect.left,
    previewLeft: previewRect?.left ?? null, previewRight: previewRect?.right ?? null, previewWidth: previewRect?.width ?? null,
    previewLabel, pulling, panes, entering, stillPulling,
    handleLabel: handle.getAttribute('aria-label'),
    hasMoreButton: Boolean(document.querySelector('[aria-label="分屏操作"]')),
  })
} catch (error) {
  document.querySelector('#result').textContent = JSON.stringify({ error: String(error), stack: error.stack })
}
`

let server
try {
  server = await createServer({ configFile: 'vite.config.core-app.ts', cacheDir: join(directory, 'vite-cache'), server: { host: '127.0.0.1', port: 0 }, plugins: [{
    name: 'split-pull-check',
    resolveId(id) { if (id === '/__split_pull_entry.js') return '\0split-pull-entry' },
    load(id) { if (id === '\0split-pull-entry') return entry },
    configureServer(s) {
      s.middlewares.use((request, response, next) => {
        if (request.url === '/__split_pull_check') { response.setHeader('Content-Type', 'text/html'); response.end(page) }
        else next()
      })
    },
  }] })
  await server.listen()
  let stdout = ''
  // A cold Vite dependency optimization can outlast the first virtual-time budget; retry only the unfinished page.
  for (let attempt = 0; attempt < 3; attempt++) {
    ({ stdout } = await promisify(execFile)(process.env.LAMTOOLS_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      ['--headless', '--disable-gpu', '--no-first-run', '--window-size=1400,900', `--user-data-dir=${join(directory, `profile-${attempt}`)}`,
        '--virtual-time-budget=15000', '--dump-dom', server.resolvedUrls.local[0] + '__split_pull_check'],
      { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, windowsHide: true, timeout: 60000 }))
    if (!/<pre id="result">loading<\/pre>/.test(stdout)) break
    await new Promise(resolve => setTimeout(resolve, 800))
  }
  const raw = stdout.match(/<pre id="result">(.*?)<\/pre>/s)?.[1]
  if (!raw || raw === 'loading') console.error(stdout.slice(0, 4000))
  assert.ok(raw && raw !== 'loading', `Fixture did not finish: ${raw}`)
  const result = JSON.parse(raw.replaceAll('&quot;', '"').replaceAll('&amp;', '&').replaceAll('&lt;', '<').replaceAll('&gt;', '>'))
  assert.equal(result.error, undefined, result.stack)
  assert.equal(result.handleLabel, '新建分屏')
  assert.equal(result.hasMoreButton, false)
  assert.equal(result.pulling, true)
  assert.equal(result.previewLabel, '向右分屏')
  assert.ok(result.previewWidth > 20, JSON.stringify(result))
  assert.ok(result.previewLeft >= result.paneLeft && result.previewRight <= result.paneRight + 1, JSON.stringify(result))
  assert.equal(result.panes, 2)
  assert.equal(result.entering, 1)
  assert.equal(result.stillPulling, false)
  console.log('PASS: drag handle previews on the pane edge, creates a second pane, and plays the entry animation.')
} finally {
  await server?.close()
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
