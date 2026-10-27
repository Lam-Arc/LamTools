// user:“如图，我不清楚这是不是你写出来的界面的设计的样子”+(用实际 Vue 宿主与生产样式重现主页面)。
import {test} from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {extname,resolve} from 'node:path';import {readFile} from 'node:fs/promises';import {pathToFileURL} from 'node:url';
const buildRequire=createRequire(resolve('core/ui/package.json'));const {createServer}=await import(pathToFileURL(buildRequire.resolve('vite')).href);const vue=(await import(pathToFileURL(buildRequire.resolve('@vitejs/plugin-vue')).href)).default;
const testRequire=createRequire(resolve('.build/excalidraw-test/package.json'));const {chromium}=testRequire('playwright-core');
test('actual Vue main page displays a usable upstream canvas',async()=>{
 const assetRoot=resolve('plugins/excalidraw');
 const assets={name:'local-excalidraw-assets',configureServer(server){server.middlewares.use('/api/core/plugin-system/excalidraw/assets',async(req,res)=>{try{const path=resolve(assetRoot,'.'+decodeURIComponent(req.url.split('?')[0]));if(!path.startsWith(assetRoot+'\\'))throw Error('bad path');const types={'.mjs':'text/javascript','.js':'text/javascript','.woff2':'font/woff2'};res.setHeader('content-type',types[extname(path)]||'application/octet-stream');res.end(await readFile(path))}catch{res.statusCode=404;res.end()}})}};
 const server=await createServer({configFile:false,root:resolve('core/ui'),plugins:[vue(),assets],resolve:{alias:{'@':resolve('core/ui/src'),'@lamtools/bundled-workflow-ui':resolve('core/src/lamtools_core/plugins/bundled/workflow/ui/index.ts')}},optimizeDeps:{noDiscovery:true},server:{host:'127.0.0.1',port:0},logLevel:'error'});
 await server.listen();const address=server.httpServer.address();const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{const page=await browser.newPage({viewport:{width:2560,height:1380}});const errors=[];page.on('pageerror',e=>errors.push(String(e)));await page.goto(`http://127.0.0.1:${address.port}/tests/fixtures/excalidraw-main/`);await page.locator('.excalidraw canvas.interactive').waitFor({timeout:20000});
  const measurements=await page.evaluate(()=>Object.fromEntries(['.workspace-main','.split-plugin-page','.split-plugin-page__host','.plugin-page-instance','.sunday-excalidraw','.sunday-excalidraw-canvas','.excalidraw canvas.interactive','[data-testid=toolbar-rectangle]'].map(selector=>[selector,document.querySelector(selector)?.getBoundingClientRect().toJSON()])));
  const toolbar = await page.getByRole('button',{name:'新建',exact:true}).evaluate(e=>{const s=getComputedStyle(e);return {height:e.getBoundingClientRect().height,background:s.backgroundColor,border:s.borderTopWidth}});
  assert.ok(toolbar.height>=28 && (toolbar.background!=='rgba(0, 0, 0, 0)' || toolbar.border!=='0px'),JSON.stringify(toolbar));
  assert.ok(measurements['.excalidraw canvas.interactive'].height>500,JSON.stringify(measurements));assert.ok(measurements['[data-testid=toolbar-rectangle]'].y<500,JSON.stringify(measurements));assert.deepEqual(errors,[]);
 }finally{await browser.close();await server.close()}
});
