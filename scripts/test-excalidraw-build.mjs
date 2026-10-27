// user:“该修就修，不用停下”+(固定上游版本并检验源码和生成产物可复现)。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
const hash=async p=>createHash('sha256').update(await readFile(p)).digest('hex');
test('original source and all generated modules reproduce from the fixed toolchain', async()=>{
 const root='.build/obsidian-excalidraw-upstream';
 assert.equal(execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),'5e4c83f6370f93d3f794ef7afb9545a6b6208c11');
 for(const [upstream,vendor] of [['src/shared/ExcalidrawData.ts','ExcalidrawData.ts'],['src/shared/excalidrawMarkdownParsing.ts','excalidrawMarkdownParsing.ts'],['src/utils/sceneDataUtils.ts','sceneDataUtils.ts'],['src/utils/excalidrawSceneUtils.ts','excalidrawSceneUtils.ts'],['src/constants/constants.ts','constants.ts']]) assert.equal(await hash(`${root}/${upstream}`),await hash(`plugins/excalidraw/vendor/${vendor}`));
 const targets=['plugins/excalidraw/ui/src/upstream-markdown.mjs','plugins/excalidraw/ui/src/upstream-markdown-writer.mjs','plugins/excalidraw/ui/mermaid.mjs','plugins/excalidraw/ui/page.mjs'];
 const before=await Promise.all(targets.map(hash));
 for(const script of ['build-excalidraw-markdown.mjs','build-excalidraw-writer.mjs','build-excalidraw-mermaid.mjs','build-excalidraw-ui.mjs'])execFileSync(process.execPath,[`scripts/${script}`],{stdio:'pipe'});
 assert.deepEqual(await Promise.all(targets.map(hash)),before);
});

test('build toolchain is independent of the bili-scroll experiment', async()=>{
 for(const script of ['build-excalidraw-markdown.mjs','build-excalidraw-writer.mjs','build-excalidraw-mermaid.mjs','build-excalidraw-ui.mjs']) assert.doesNotMatch(await readFile(`scripts/${script}`,'utf8'),/plugin-rebuild/);
});
