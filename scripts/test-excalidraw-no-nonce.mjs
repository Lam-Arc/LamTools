// user:“如图，我不清楚这是不是你写出来的界面的设计的样子”+(模拟打包页无 nonce 时，实测画布、工具栏和样式)。
import {test} from 'node:test';import assert from 'node:assert/strict';import {createServer} from 'node:http';import {readFile} from 'node:fs/promises';import {createRequire} from 'node:module';import {extname,resolve} from 'node:path';
const require=createRequire(resolve('.build/excalidraw-toolchain/package.json'));const {build}=require('esbuild');const {chromium}=createRequire(resolve('.build/excalidraw-test/package.json'))('playwright-core');
const plugin=resolve('plugins/excalidraw/ui');
test('actual canvas stays visible when packaged CSP forbids inline style',async()=>{
 const module=(await build({entryPoints:[resolve('core/ui/src/plugins/styles.ts')],bundle:true,format:'esm',write:false})).outputFiles[0].text;
 const server=createServer(async(req,res)=>{try{const url=decodeURIComponent(req.url.split('?')[0]);res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-missing' blob:; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'");
  if(url==='/'){res.setHeader('content-type','text/html');res.end('<html><head><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script type="module" src="/start.mjs"></script></body></html>');return;}
  if(url==='/fixture.css'){res.setHeader('content-type','text/css');res.end('#root{height:750px}');return;}
  if(url==='/styles.mjs'){res.setHeader('content-type','text/javascript');res.end(module);return;}
  if(url==='/start.mjs'){res.setHeader('content-type','text/javascript');res.end(`import {attachPluginStyle} from '/styles.mjs';import {mount} from '/page.mjs';const root=document.getElementById('root');window.cleanup=mount(root,{rpc:async()=>({}),signal:new AbortController().signal,addStyle:css=>attachPluginStyle(root,css,'excalidraw')});`);return;}
  const path=resolve(plugin,'.'+url);if(!path.startsWith(plugin+'\\'))throw Error('bad path');const types={'.mjs':'text/javascript','.js':'text/javascript','.woff2':'font/woff2'};res.setHeader('content-type',types[extname(path)]||'application/octet-stream');res.end(await readFile(path));
 }catch{res.statusCode=404;res.end()}});await new Promise(done=>server.listen(0,'127.0.0.1',done));const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{const page=await browser.newPage({viewport:{width:1600,height:900}});const errors=[];page.on('pageerror',e=>errors.push(String(e)));await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.locator('.excalidraw canvas.interactive').waitFor({timeout:20000});await page.waitForFunction(()=>{const el=document.querySelector('[data-testid=toolbar-rectangle]');return el&&el.getBoundingClientRect().height<70},null,{timeout:5000});
  assert.ok(await page.locator('link[data-plugin-style="excalidraw"]').count());assert.ok((await page.locator('.excalidraw canvas.interactive').boundingBox()).height>500);assert.deepEqual(errors,[]);
  await page.evaluate(()=>window.cleanup());assert.equal(await page.locator('link[data-plugin-style="excalidraw"]').count(),0);
 }finally{await browser.close();await new Promise(done=>server.close(done))}
});
