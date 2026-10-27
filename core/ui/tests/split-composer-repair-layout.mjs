// user:“分屏后输入栏会出bug”+(通过本地浏览器引擎检查真实共享组件的命中、中文输入和布局；不操作桌面应用)。
import { createServer } from 'vite'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import assert from 'node:assert/strict'
const directory = mkdtempSync(join(tmpdir(), 'lam-composer-check-'))
const page = `<!doctype html><meta charset="utf-8"><div id="app"></div><pre id="result">loading</pre><script type="module" src="/__composer_entry.js"></script>`
const entry = `
import { createApp, h, ref, nextTick } from 'vue'
import ComposerBar from '/src/components/ComposerBar.vue'
import Editor from '/src/components/InlineFileComposer.vue'
import Controls from '/src/components/CoreExecutionControls.vue'
import Attach from '/src/components/AttachmentSourceMenu.vue'
import '/src/styles/variables.css'; import '/src/styles/base.css'; import '/src/styles/layout.css'; import '/src/styles/split-workspace.css'; import '/src/styles/auxiliary-chat.css';
const draft=ref('');
createApp({ setup(){return ()=>h('div', {class:'workspace-shell workspace-shell--split workspace-shell--composer-center',style:'--main-left:0px;--main-right:0px;--split-primary-width:650px;--split-primary-x:0px;--split-primary-bottom:0px'}, [h('div',{id:'pane',style:'position:absolute;left:0;top:0;width:360px;height:300px'}, [h('div',{class:'auxiliary-chat'},[h('header',{class:'split-content-toolbar'},'主聊天助手'),h('div',{class:'auxiliary-scroll-area'},'内容'),h(ComposerBar,{class:'auxiliary-composer',variant:'embedded'}, {textarea:()=>h(Editor,{modelValue:draft.value,'onUpdate:modelValue':value=>draft.value=value,placeholder:'给 Sunday 发送任务...'}),tools:()=>h(Controls,{modelValue:'m',thinkingMode:'high',thinkingModeOptions:[{value:'high',label:'高'}],modelOptions:[{value:'m',label:'模型'}],showRuntimeMenu:false},{leading:()=>h(Attach)})})])])])}}).mount('#app');
try {
 const results=[]; const pane=document.querySelector('#pane');
 for(const width of [260,360,620]) for(const height of [220,300,700]) {
   draft.value='';pane.style.width=width+'px';pane.style.height=height+'px';await nextTick();await new Promise(r=>setTimeout(r,40));
   const editor=pane.querySelector('[role=textbox]'), hint=pane.querySelector('.cm-placeholder');editor.blur();
   const rect=hint.getBoundingClientRect(), target=document.elementFromPoint(rect.left+2,rect.top+5);
   target.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true,button:0}));
   const focused=document.activeElement===editor;
   document.execCommand('insertText',false,'中文问题');await new Promise(r=>setTimeout(r,30));
   const pr=pane.getBoundingClientRect(), cr=pane.querySelector('form').getBoundingClientRect();
   results.push({width,height,focused,typed:draft.value==='中文问题',inside:cr.left>=pr.left&&cr.right<=pr.right+1&&cr.bottom<=pr.bottom+1});
 }
 document.querySelector('#result').textContent=JSON.stringify(results);
} catch(error) {document.querySelector('#result').textContent=JSON.stringify({error:String(error),stack:error.stack});}
`
let server
try {
  server = await createServer({ configFile: 'vite.config.core-app.ts', server: { host: '127.0.0.1', port: 0 }, plugins: [{ name: 'composer-check', resolveId(id) { if (id === '/__composer_entry.js') return '\0composer-check' }, load(id) { if (id === '\0composer-check') return entry }, configureServer(s) {
    s.middlewares.use((req, res, next) => {
      if (req.url === '/__composer_check') { res.setHeader('Content-Type', 'text/html'); res.end(page) }
      else next()
    })
  } }] })
  await server.listen()
  const { stdout } = await promisify(execFile)(process.env.LAMTOOLS_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', ['--headless', '--disable-gpu', '--no-first-run', '--window-size=1400,900', `--user-data-dir=${join(directory, 'profile')}`, '--virtual-time-budget=15000', '--dump-dom', server.resolvedUrls.local[0] + '__composer_check'], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, windowsHide: true, timeout: 60000 })
  const result = stdout.match(/<pre id="result">(.*?)<\/pre>/s)?.[1]
  assert.ok(result && result !== 'loading', `Fixture did not finish: ${result}`)
  const rows = JSON.parse(result.replaceAll('&quot;', '"').replaceAll('&amp;', '&'))
  assert.ok(Array.isArray(rows), JSON.stringify(rows)); assert.equal(rows.length, 9)
  for (const row of rows) assert.ok(row.focused && row.typed && row.inside, JSON.stringify(row))
  console.log('PASS: real shared composer, 9 pane sizes, pointer hit → focus → Chinese text; composer stays within pane.')
} finally {
  await server?.close()
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
