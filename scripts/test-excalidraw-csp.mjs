// user:“该修就修，不用停下”+(真实浏览器验证桌面策略允许插件后端提供原版字体)。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(resolve('.build/excalidraw-test/package.json'));
const { chromium } = require('playwright-core');

test('desktop CSP loads a plugin font across loopback ports', async () => {
  const config = JSON.parse(await readFile('core/desktop/src-tauri/tauri.conf.json','utf8'));
  const csp = config.app.security.csp;
  const font = await readFile('plugins/excalidraw/ui/fonts/Assistant/Assistant-Regular.woff2');
  const asset = createServer((req,res)=>{res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('content-type','font/woff2');res.end(font)});
  await new Promise(done=>asset.listen(0,'127.0.0.1',done));
  const web = createServer((req,res)=>{res.setHeader('Content-Security-Policy',csp);res.setHeader('content-type','text/html');res.end('<html><body>font test</body></html>')});
  await new Promise(done=>web.listen(0,'127.0.0.1',done));
  const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  try {
    const page=await browser.newPage(); await page.goto(`http://127.0.0.1:${web.address().port}/`);
    const result=await page.evaluate(async url=>{try{const font=new FontFace('test-local',`url(${url})`);await font.load();return 'loaded'}catch(error){return String(error)}}, `http://127.0.0.1:${asset.address().port}/test.woff2`);
    assert.equal(result,'loaded');
  } finally {await browser.close();await new Promise(done=>web.close(done));await new Promise(done=>asset.close(done));}
});

test('desktop CSP allows temporary image previews used by the upstream canvas', async () => {
  const config = JSON.parse(await readFile('core/desktop/src-tauri/tauri.conf.json','utf8'));
  const server=createServer((req,res)=>{res.setHeader('Content-Security-Policy',config.app.security.csp);res.setHeader('content-type','text/html');res.end('<html><body>image test</body></html>')});
  await new Promise(done=>server.listen(0,'127.0.0.1',done));
  const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  try {
    const page=await browser.newPage(); await page.goto(`http://127.0.0.1:${server.address().port}/`);
    const result=await page.evaluate(()=>new Promise(resolve=>{const bytes=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+8iUAAAAASUVORK5CYII='),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));const img=new Image();img.onload=()=>{URL.revokeObjectURL(url);resolve('loaded')};img.onerror=()=>{URL.revokeObjectURL(url);resolve('blocked')};img.src=url;}));
    assert.equal(result,'loaded');
  } finally {await browser.close();await new Promise(done=>server.close(done));}
});
