// user:“该修就修，不用停下”+(静态打包上游插件所用的原始画布与样式，避免执行解压后的动态脚本)。
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { cp, readFile } from 'node:fs/promises';
const require = createRequire(resolve('.build/excalidraw-toolchain/package.json'));
const { build } = require('esbuild');
const dependencies = resolve('.build/obsidian-excalidraw-upstream/node_modules');
const ui = resolve('plugins/excalidraw/ui');
const upstream = resolve(dependencies, '@zsviczian/excalidraw/dist/obsidian');
await build({ entryPoints: [resolve(ui, 'src/page.mjs')], outfile: resolve(ui, 'page.mjs'), bundle: true, format: 'esm', minify: true, target: 'es2022', nodePaths: [dependencies], define: { 'process.env.NODE_ENV': '"production"' }, legalComments: 'eof', plugins: [{ name: 'original-excalidraw', setup(build) {
  build.onResolve({ filter: /^upstream-excalidraw-(runtime|css)$/ }, args => ({ path: args.path, namespace: 'original' }));
  build.onLoad({ filter: /.*/, namespace: 'original' }, async args => {
    if (args.path.endsWith('css')) return { contents: await readFile(resolve(upstream, 'excalidraw.production.min.css'), 'utf8'), loader: 'text' };
    const source = await readFile(resolve(upstream, 'excalidraw.production.min.js'), 'utf8');
    return { contents: `import React from 'react';\nimport * as ReactDOMLegacy from 'react-dom';\nimport * as ReactDOMClient from 'react-dom/client';\nimport * as ReactJSXRuntime from 'react/jsx-runtime';\nimport * as ReactJSXDevRuntime from 'react/jsx-dev-runtime';\nconst ReactDOM = {...ReactDOMLegacy,...ReactDOMClient};\nexport function createExcalidrawRuntime() {\n${source}\nreturn ExcalidrawLib;\n}`, loader: 'js', resolveDir: dependencies };
  });
}}] });

await cp(resolve(dependencies, '@zsviczian/excalidraw/dist/prod/fonts'), resolve(ui, 'fonts'), { recursive: true });
