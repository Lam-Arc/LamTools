// user:“如图，我不清楚这是不是你写出来的界面的设计的样子”+(打包页没有可借用的 nonce 时，插件样式仍需正常加载并清理)。
import {test} from 'node:test';import assert from 'node:assert/strict';import {createServer} from 'node:http';import {readFile} from 'node:fs/promises';import {createRequire} from 'node:module';import {resolve} from 'node:path';
const require=createRequire(resolve('.build/excalidraw-toolchain/package.json'));const {build}=require('esbuild');const {chromium}=createRequire(resolve('.build/excalidraw-test/package.json'))('playwright-core');
test('plugin styles work with nonce-only CSP even when no nonce-bearing element exists',async()=>{
 const result=await build({entryPoints:[resolve('core/ui/src/plugins/styles.ts')],bundle:true,format:'esm',write:false});const module=result.outputFiles[0].text;
 const server=createServer((req,res)=>{res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-unavailable' blob:");if(req.url==='/'){res.setHeader('content-type','text/html');res.end('<div id="probe">内容</div><script type="module" src="/start.mjs"></script>');}else if(req.url==='/start.mjs'){res.setHeader('content-type','text/javascript');res.end(`import {attachPluginStyle} from '/styles.mjs';window.removeStyle=attachPluginStyle(document.getElementById('probe'), '#probe{color:rgb(3,17,201)}', 'probe');`)}else{res.setHeader('content-type','text/javascript');res.end(module)}});
 await new Promise(done=>server.listen(0,'127.0.0.1',done));const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{const page=await browser.newPage();await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.waitForFunction(()=>getComputedStyle(document.getElementById('probe')).color==='rgb(3, 17, 201)',null,{timeout:4000});await page.evaluate(()=>window.removeStyle());assert.notEqual(await page.locator('#probe').evaluate(e=>getComputedStyle(e).color),'rgb(3, 17, 201)')}
 finally{await browser.close();await new Promise(done=>server.close(done))}
});

test('a blocked fallback displays a recoverable error instead of a blank plugin page',async()=>{
 const result=await build({entryPoints:[resolve('core/ui/src/plugins/styles.ts')],bundle:true,format:'esm',write:false});const module=result.outputFiles[0].text;
 const server=createServer((req,res)=>{res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-unavailable'");if(req.url==='/'){res.setHeader('content-type','text/html');res.end('<div id="host"><div id="probe"></div></div><script type="module" src="/start.mjs"></script>')}else if(req.url==='/start.mjs'){res.setHeader('content-type','text/javascript');res.end(`import {attachPluginStyle} from '/styles.mjs';window.removeStyle=attachPluginStyle(document.getElementById('probe'),'#probe{color:red}','probe');`)}else{res.setHeader('content-type','text/javascript');res.end(module)}});
 await new Promise(done=>server.listen(0,'127.0.0.1',done));const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{const page=await browser.newPage();await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.getByRole('alert').getByText('插件样式无法加载，请刷新页面或检查桌面版本').waitFor({timeout:4000});await page.evaluate(()=>window.removeStyle());assert.equal(await page.getByRole('alert').count(),0)}
 finally{await browser.close();await new Promise(done=>server.close(done))}
});

test('closing immediately cannot leave a delayed style error behind',async()=>{
 const module=(await build({entryPoints:[resolve('core/ui/src/plugins/styles.ts')],bundle:true,format:'esm',write:false})).outputFiles[0].text;
 const server=createServer((req,res)=>{res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-unavailable'");if(req.url==='/'){res.setHeader('content-type','text/html');res.end('<div id="host"><div id="probe"></div></div><script type="module" src="/start.mjs"></script>')}else if(req.url==='/start.mjs'){res.setHeader('content-type','text/javascript');res.end(`import {attachPluginStyle} from '/styles.mjs';const cleanup=attachPluginStyle(document.getElementById('probe'),'#probe{color:red}','probe');cleanup();window.finished=true;`)}else{res.setHeader('content-type','text/javascript');res.end(module)}});
 await new Promise(done=>server.listen(0,'127.0.0.1',done));const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{const page=await browser.newPage();await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.waitForFunction(()=>window.finished);await page.evaluate(()=>new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done))));assert.equal(await page.getByRole('alert').count(),0)}
 finally{await browser.close();await new Promise(done=>server.close(done))}
});
