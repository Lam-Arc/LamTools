// user:“范围不对，光标出格了”+(通过本地浏览器引擎检查主区与辅助输入栏内提示、光标、换行和滚动的边界；不操作桌面应用)。
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
const draft=ref(''), context=ref('auxiliary');
createApp({ setup(){return ()=>h('div', {class:context.value==='main'?'workspace-shell workspace-shell--composer-center':'workspace-shell workspace-shell--split workspace-shell--composer-center',style:'--main-left:0px;--main-right:0px;--split-primary-width:650px;--split-primary-x:0px;--split-primary-bottom:0px'}, [h('div',{id:'pane',style:'position:absolute;left:0;top:0;width:360px;height:300px'}, [h('div',{class:context.value==='auxiliary'?'auxiliary-chat':'test-chat',style:'display:flex;flex-direction:column;height:100%;min-height:0'},[h('header',{class:'split-content-toolbar'},'主聊天助手'),h('div',{class:'auxiliary-scroll-area'},'内容'),h(ComposerBar,{class:context.value==='auxiliary'?'auxiliary-composer':'',variant:context.value==='auxiliary'?'embedded':'floating'}, {textarea:()=>h(Editor,{modelValue:draft.value,'onUpdate:modelValue':value=>draft.value=value,placeholder:'给 Sunday 发送任务...'}),tools:()=>h(Controls,{modelValue:'m',thinkingMode:'high',thinkingModeOptions:[{value:'high',label:'高'}],modelOptions:[{value:'m',label:'模型'}],showRuntimeMenu:false},{leading:()=>h(Attach)})})])])])}}).mount('#app');
try {
 const results=[]; const pane=document.querySelector('#pane');
 for(const mode of ['main','split','auxiliary']) for(const width of [260,360,620]) for(const height of [220,300,700]) {
   context.value=mode;document.querySelector('.workspace-shell').style.setProperty('--content-width',width+'px');document.querySelector('.workspace-shell').style.setProperty('--split-primary-width',width+'px');
   draft.value='';pane.style.width=width+'px';pane.style.height=height+'px';await nextTick();await new Promise(r=>setTimeout(r,40));
   const editor=pane.querySelector('[role=textbox]'), hint=pane.querySelector('.cm-placeholder');editor.blur();
   const rect=hint.getBoundingClientRect(), firstForm=pane.querySelector('form').getBoundingClientRect(), hintInset=rect.left-firstForm.left, target=document.elementFromPoint(rect.left+2,rect.top+5);
   target.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true,button:0}));
   const focused=document.activeElement===editor;
   document.execCommand('insertText',false,'中文问题');await new Promise(r=>setTimeout(r,30));
   const pr=pane.getBoundingClientRect(), cr=pane.querySelector('form').getBoundingClientRect();
   const range=window.getSelection().getRangeAt(0).getBoundingClientRect();
   const safe=r=>{const f=pane.querySelector('form').getBoundingClientRect(), toolbar=pane.querySelector('.composer-bottom').getBoundingClientRect();return r.left>=f.left+12&&r.right<=f.right-12&&r.top>=f.top+8&&r.bottom<=toolbar.top+1};
   const shortSafe=safe(range), typed=draft.value==='中文问题';
   document.execCommand('insertText',false,'中文长文本自动换行。'.repeat(120));await new Promise(r=>setTimeout(r,40));
   const scroller=pane.querySelector('.cm-scroller');scroller.scrollTop=scroller.scrollHeight;await new Promise(r=>setTimeout(r,40));
   const longRange=window.getSelection().getRangeAt(0).getBoundingClientRect();
   results.push({mode,width,height,focused,typed,hintInset,shortSafe,longSafe:safe(longRange),longRange:longRange.toJSON(),form:pane.querySelector('form').getBoundingClientRect().toJSON(),toolbar:pane.querySelector('.composer-bottom').getBoundingClientRect().toJSON(),scrollTop:pane.querySelector('.cm-scroller').scrollTop});
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
  assert.ok(Array.isArray(rows), JSON.stringify(rows)); assert.equal(rows.length, 27)
  for (const row of rows) assert.ok(row.focused && row.typed && row.hintInset>=12 && row.shortSafe && row.longSafe, JSON.stringify(row))
  console.log('PASS: placeholder and native caret stay inset, including long wrapped text, across 27 normal/split/auxiliary sizes.')
} finally {
  await server?.close()
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
