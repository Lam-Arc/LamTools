// user:“如图，我不清楚这是不是你写出来的界面的设计的样子”+(在桌面主界面真实样式与 nonce 策略下验证画布布局)。
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {extname,resolve} from 'node:path';
const require=createRequire(resolve('.build/excalidraw-test/package.json'));
const {chromium}=require('playwright-core');
const desktop=resolve('core/desktop/dist'), plugin=resolve(process.env.EXCALIDRAW_UI_DIR || 'plugins/excalidraw/ui');
test('main workspace renders canvas with installed desktop CSS and nonce policy',async()=>{
 const index=await readFile(resolve(desktop,'index.html'),'utf8');
 const links=[...index.matchAll(/<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g)].map(m=>m[1]);
 assert.ok(links.length>0);
 const server=createServer(async(req,res)=>{try{
  const url=decodeURIComponent(req.url.split('?')[0]);
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' 'nonce-host-test'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'");
  if(url==='/'){res.setHeader('content-type','text/html');res.end(`<html><head>${links.map(x=>`<link rel="stylesheet" href="/desktop/${x.replace(/^\.\//,'')}">`).join('')}<style nonce="host-test">.fixture-main{height:800px;display:flex;flex-direction:column}.fixture-page{height:100%;min-height:0;display:flex;flex-direction:column}.fixture-host{flex:1;min-height:0;overflow:auto;padding:12px}</style></head><body><main class="fixture-main"><div class="workspace-main-default"><div class="fixture-page"><header>Excalidraw</header><div class="fixture-host"><div id="root" class="plugin-page-instance"></div></div></div></div></main><script type="module" src="/fixture.mjs"></script></body></html>`);return;}
  if(url==='/fixture.mjs'){res.setHeader('content-type','text/javascript');res.end(`import {mount} from '/plugin/page.mjs'; const root=document.getElementById('root'); window.dispose=mount(root,{rpc:async()=>({}),signal:new AbortController().signal,addStyle(css){let style=document.createElement('style');let nonce=document.querySelector('style[nonce]')?.nonce||document.querySelector('link[nonce]')?.nonce;if(nonce)style.nonce=nonce;style.textContent=css;document.head.append(style);return()=>style.remove()}});`);return;}
  const base=url.startsWith('/desktop/')?desktop:plugin; const rel=url.startsWith('/desktop/')?url.slice(9):url.slice(8);const path=resolve(base,rel);if(!path.startsWith(base+'\\'))throw Error('invalid');
  const types={'.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.svg':'image/svg+xml'};res.setHeader('content-type',types[extname(path)]||'application/octet-stream');res.end(await readFile(path));
 }catch{res.statusCode=404;res.end()}});
 await new Promise(done=>server.listen(0,'127.0.0.1',done));
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{const page=await browser.newPage({viewport:{width:1600,height:900}});let errors=[];page.on('pageerror',e=>errors.push(String(e)));await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.locator('.excalidraw canvas.interactive').waitFor({timeout:20000});
 const result=await page.evaluate(()=>{const root=document.querySelector('.plugin-page-instance'),canvas=document.querySelector('.excalidraw canvas.interactive'),tool=document.querySelector('[data-testid=toolbar-rectangle]'),style=[...document.querySelectorAll('style')].find(e=>e.textContent.includes('.sunday-excalidraw{'));return {root:root.getBoundingClientRect().toJSON(),canvas:canvas.getBoundingClientRect().toJSON(),tool:tool.getBoundingClientRect().toJSON(),rules:style?.sheet?.cssRules.length||0}});
 assert.ok(result.rules>100,'plugin CSS should be applied');assert.ok(result.canvas.height>=500,JSON.stringify(result));assert.ok(result.tool.height<70,JSON.stringify(result));assert.deepEqual(errors,[]);
 }finally{await browser.close();await new Promise(done=>server.close(done))}
});
