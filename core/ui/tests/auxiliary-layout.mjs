// user:“更适配新的UI”+(验证窄侧屏及上下分屏中，原文可展开、消息可滚动、输入仍可达)。
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'
const directory = mkdtempSync(join(tmpdir(), 'lam-auxiliary-layout-'))
try {
  const css = ['variables.css', 'base.css', 'split-workspace.css', 'auxiliary-chat.css'].map(name => readFileSync(resolve('src/styles', name), 'utf8').replace(/^\uFEFF/, '')).join('\n')
  const fixture = join(directory, 'auxiliary.html')
  writeFileSync(fixture, `<!doctype html><meta charset="utf-8"><style>${css}
    body { margin:0; } .ui-select { width:140px; } .ui-select button { max-width:100%; overflow:hidden; white-space:nowrap; }
  </style><div id="pane"><div class="auxiliary-chat">
  <header class="split-content-toolbar auxiliary-toolbar"><span class="auxiliary-caption">辅助对话</span><div class="ui-select"><button>当前使用的模型名称</button></div><button class="split-icon-button">↗</button></header>
  <details open class="auxiliary-reference"><summary><span>保留来源原文和之前的问答</span></summary><blockquote>${'原文内容。'.repeat(160)}</blockquote></details>
  <div class="auxiliary-scroll-area"><div class="auxiliary-transcript">${'<p>持续追加的回答。</p>'.repeat(60)}</div></div>
  <form class="auxiliary-composer"><textarea style="height:120px" rows="2">待发送的问题</textarea><footer><span>Enter 发送 · Shift + Enter 换行</span><button>发送</button></footer></form>
  </div></div><script>
    const results=[]; const pane=document.querySelector('#pane');
    for (const width of [260,360,620]) for (const height of [300,700]) {
      pane.style.width=width+'px'; pane.style.height=height+'px';
      const root=pane.getBoundingClientRect(), composer=document.querySelector('form').getBoundingClientRect(), transcript=document.querySelector('.auxiliary-transcript');
      results.push({width,height,composerInside:composer.bottom<=root.bottom+1&&composer.right<=root.right+1,overflow:transcript.scrollHeight>transcript.clientHeight,scroll:getComputedStyle(transcript).overflowY});
    }
    document.body.innerHTML='<pre id="result">'+JSON.stringify(results)+'</pre>';
  </script>`)
  const browser = process.env.LAMTOOLS_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
  const output = execFileSync(browser, ['--headless', '--window-size=1400,900', '--disable-gpu', '--no-first-run', '--no-default-browser-check', `--user-data-dir=${join(directory, 'profile')}`, '--dump-dom', pathToFileURL(fixture).href], { encoding: 'utf8', timeout: 45000, stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true })
  const results = JSON.parse(output.match(/<pre id="result">(.*?)<\/pre>/s)?.[1] || 'null')
  assert.ok(results)
  for (const result of results) { assert.ok(result.composerInside, JSON.stringify(result)); assert.ok(result.overflow); assert.equal(result.scroll, 'auto') }
  console.log('PASS: 260 / 360 / 620px panes, 300 / 700px heights, expanded quote, growing input, scrolling transcript.')
} finally { rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 }) }
