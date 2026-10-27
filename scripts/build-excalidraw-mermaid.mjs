// user:“该修就修，不用停下”+(静态打包原版 Extras 所需的 Mermaid 2.2.2 实现)。
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const require=createRequire(resolve('.build/excalidraw-toolchain/package.json'));
const {build}=require('esbuild');
const dependencies=resolve('.build/obsidian-excalidraw-upstream/node_modules');
await build({stdin:{contents:"export { parseMermaidToExcalidraw } from '@excalidraw/mermaid-to-excalidraw';",resolveDir:dependencies,loader:'js'},outfile:resolve('plugins/excalidraw/ui/mermaid.mjs'),bundle:true,format:'esm',target:'es2022',minify:true,define:{'process.env.NODE_ENV':'"production"'},legalComments:'eof'});
