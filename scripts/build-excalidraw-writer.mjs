// user:“该修就修，不用停下”+(从原版完整源码提取原始 Markdown 生成方法和场景 ID 更新方法)。
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { readFile } from 'node:fs/promises';
const require=createRequire(resolve('.build/excalidraw-toolchain/package.json'));
const {build}=require('esbuild');
const folder=resolve('plugins/excalidraw');
const data=await readFile(resolve(folder,'vendor/ExcalidrawData.ts'),'utf8');
const utils=await readFile(resolve(folder,'vendor/excalidrawSceneUtils.ts'),'utf8');
const begin=data.indexOf('  generateMDBase(deletedElements:');
const end=data.indexOf('\n  async generateMDAsync(',begin);
if (begin<0 || end<0) throw Error('upstream writer method is missing');
const method=data.slice(begin,end);
const contents=`const MARKDOWN_IMAGE_EMBEDDED_FILE_TOKEN = 'markdown-image';\nclass OriginalWriter {\n${method}\n}\nexport const generateMDBase = OriginalWriter.prototype.generateMDBase;\n${utils}`;
await build({stdin:{contents,loader:'ts',resolveDir:resolve('.build/obsidian-excalidraw-upstream/node_modules')},outfile:resolve(folder,'ui/src/upstream-markdown-writer.mjs'),bundle:true,format:'esm',target:'es2022',legalComments:'eof'});
