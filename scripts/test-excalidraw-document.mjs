// user:“该修就修，不用停下”+(原版画图数据能由宿主存取，外部修改后不覆盖原文件)。
import test from 'node:test';
import assert from 'node:assert/strict';
import { openDrawing, saveDrawing } from '../plugins/excalidraw/ui/src/document.mjs';

test('original Excalidraw file opens and preserves drawing elements when saved', async () => {
  const original = JSON.stringify({ type: 'excalidraw', version: 2, source: 'https://excalidraw.com', elements: [{ id: 'a', type: 'rectangle', x: 10, y: 20 }], appState: { viewBackgroundColor: '#fff' }, files: {} });
  const calls = [];
  const rpc = async (name, args) => { calls.push([name, args]); return name.endsWith('read') ? { content: original } : { saved: true }; };
  const drawing = await openDrawing(rpc, '绘图.excalidraw');
  assert.equal(drawing.scene.elements[0].id, 'a');
  await saveDrawing(rpc, drawing, { ...drawing.scene, elements: [...drawing.scene.elements, { id: 'b', type: 'ellipse' }] });
  assert.equal(calls[1][1].original, original);
  assert.deepEqual(JSON.parse(calls[1][1].content).elements.map(x => x.id), ['a', 'b']);
});

test('failed save keeps last successfully read baseline', async () => {
  const original = '{"type":"excalidraw","elements":[]}';
  const drawing = await openDrawing(async () => ({ content: original }), 'x.excalidraw');
  await assert.rejects(saveDrawing(async () => { throw new Error('conflict'); }, drawing, drawing.scene), /conflict/);
  assert.equal(drawing.original, original);
});

test('original Markdown drawing opens without pretending unsupported save is safe', async () => {
  const scene = JSON.stringify({ type: 'excalidraw', version: 2, elements: [{ id: 'a', type: 'rectangle' }, { id: 'text1', type: 'text', text:'链接文本' }], appState: {}, files: {} });
  const original = `---\nexcalidraw-plugin: parsed\n---\n用户说明\n\n# Excalidraw Data\n\n## Text Elements\n\n## Drawing\n\`\`\`json\n${scene}\n\`\`\`\n%%\n`;
  const drawing = await openDrawing(async () => ({content: original}), '原版.excalidraw.md');
  assert.equal(drawing.scene.elements[0].id, 'a');
  assert.equal(drawing.readOnly, true);
  await assert.rejects(saveDrawing(async () => ({saved:true}), drawing, drawing.scene), /Markdown/);
});

test('a new Markdown drawing uses the original format and can be reopened', async () => {
  const drawing = { path:'new.excalidraw.md', original:null, markdown:true, scene:{type:'excalidraw',elements:[],appState:{},files:{}} };
  let written = '';
  await saveDrawing(async (method,args) => { written = args.content; assert.equal(args.original,null); return {saved:true}; }, drawing, drawing.scene);
  assert.match(written,/excalidraw-plugin: parsed/); assert.match(written,/```compressed-json/);
  assert.deepEqual((await openDrawing(async()=>({content:written}), drawing.path)).scene.elements,[]);
});

test('simple original Markdown drawing can save without changing user text outside the scene', async () => {
  const original = '---\nexcalidraw-plugin: parsed\n---\n用户备注\n\n# Excalidraw Data\n\n## Text Elements\n\n## Drawing\n```json\n{"type":"excalidraw","version":2,"elements":[],"appState":{},"files":{}}\n```\n%%\n末尾保留\n';
  const requests=[]; const rpc=async(method,args)=>{requests.push([method,args]);return method.endsWith('read')?{content:original}:{saved:true}};
  const drawing=await openDrawing(rpc,'test.excalidraw.md');
  assert.equal(drawing.readOnly,false);
  await saveDrawing(rpc,drawing,{...drawing.scene,elements:[{id:'rect1',type:'rectangle'}]});
  const content=requests[1][1].content;
  assert.ok(content.startsWith('---\nexcalidraw-plugin: parsed\n---\n用户备注'));
  assert.ok(content.endsWith('```\n%%\n末尾保留\n'));
  assert.equal(JSON.parse(content.split('```json\n')[1].split('\n```')[0]).elements[0].id,'rect1');
});

test('compressed upstream Markdown remains compressed and reopens after save', async () => {
  const { compress } = await import('../plugins/excalidraw/ui/src/upstream-markdown.mjs');
  const scene = {type:'excalidraw',version:2,elements:[],appState:{},files:{}};
  let stored = `---\nexcalidraw-plugin: parsed\n---\n\n# Excalidraw Data\n\n## Text Elements\n\n## Drawing\n\`\`\`compressed-json\n${compress(JSON.stringify(scene))}\n\`\`\`\n%%\n`;
  const rpc=async(method,args)=>{if(method.endsWith('read'))return {content:stored};assert.equal(args.original,stored);stored=args.content;return {saved:true}};
  const drawing=await openDrawing(rpc,'compressed.excalidraw.md');
  await saveDrawing(rpc,drawing,{...drawing.scene,elements:[{id:'r',type:'rectangle'}]});
  assert.match(stored,/```compressed-json/);
  assert.equal((await openDrawing(rpc,'compressed.excalidraw.md')).scene.elements[0].id,'r');
});

test('unsupported internal links in Markdown are rejected before overwriting it', async () => {
  const original = '---\nexcalidraw-plugin: parsed\n---\n\n# Excalidraw Data\n\n## Text Elements\n\n## Drawing\n```json\n{"type":"excalidraw","elements":[],"appState":{},"files":{}}\n```\n%%\n';
  let wrote=false;const rpc=async(method)=>method.endsWith('read')?{content:original}:(wrote=true,{saved:true});
  const drawing=await openDrawing(rpc,'test.excalidraw.md');
  await assert.rejects(saveDrawing(rpc,drawing,{...drawing.scene,elements:[{id:'t',type:'text',text:'[[linked document]]',rawText:'[[linked document]]'}]}), /Markdown/);
  assert.equal(wrote,false);
});

test('upstream Markdown generator preserves text block references and linked container IDs', async () => {
  const { generateMDBase, updateElementIdsInScene } = await import('../plugins/excalidraw/ui/src/upstream-markdown-writer.mjs');
  const scene={type:'excalidraw',version:2,source:'test',appState:{},files:{},elements:[
    {id:'container',type:'rectangle',boundElements:[{id:'longtextid',type:'text'}]},
    {id:'longtextid',type:'text',containerId:'container',rawText:'普通文字',text:'普通文字'}]};
  updateElementIdsInScene(scene,scene.elements[1],'ab12cd34');
  assert.equal(scene.elements[0].boundElements[0].id,'ab12cd34');
  const state={scene,plugin:{settings:{syncElementLinkWithText:false,addDummyTextElement:false}},textElementCommentedOut:false,
    textElements:new Map([['ab12cd34',{raw:'普通文字'}]]),elementLinks:new Map(),equations:new Map(),files:new Map(),markdownImages:new Map()};
  const result=generateMDBase.call(state,[]);
  assert.match(result.outString,/普通文字 \^ab12cd34/);
  assert.equal(JSON.parse(result.sceneJSONstring).elements[1].id,'ab12cd34');
});

test('plain Markdown text is indexed using the original generator and stable eight-character IDs', async () => {
  const original = '---\nexcalidraw-plugin: parsed\n---\n备注\n\n# Excalidraw Data\n\n## Text Elements\n\n## Drawing\n```json\n{"type":"excalidraw","elements":[],"appState":{},"files":{}}\n```\n%%\n尾注\n';
  let stored = original;
  const rpc=async(method,args)=>{if(method.endsWith('read'))return {content:stored}; assert.equal(args.original,stored);stored=args.content;return {saved:true}};
  const drawing=await openDrawing(rpc,'plain.excalidraw.md');
  const scene={...drawing.scene,elements:[{id:'box',type:'rectangle',boundElements:[{id:'long-text-id',type:'text'}]}, {id:'long-text-id',type:'text',containerId:'box',rawText:'简单文字',text:'简单文字',originalText:'简单文字'}]};
  await saveDrawing(rpc,drawing,scene);
  const match=stored.match(/简单文字 \^([a-zA-Z0-9]{8})/); assert.ok(match);
  assert.ok(stored.includes('备注') && stored.endsWith('```\n%%\n尾注\n'));
  const next=await openDrawing(rpc,'plain.excalidraw.md');
  assert.equal(next.readOnly,false);
  const text=next.scene.elements.find(e=>e.type==='text');
  assert.equal(text.id,match[1]); assert.equal(next.scene.elements[0].boundElements[0].id,text.id);
  await saveDrawing(rpc,drawing,scene);
  assert.equal(stored.match(/简单文字 \^([a-zA-Z0-9]{8})/)[1],match[1]);
});

test('original commented text section remains editable after save and reload', async () => {
  let stored='---\nexcalidraw-plugin: parsed\n---\n\n# Excalidraw Data\n\n## Text Elements\n\n%%\n## Drawing\n```json\n{"type":"excalidraw","elements":[],"appState":{},"files":{}}\n```\n%%\n';
  const rpc=async(method,args)=>method.endsWith('read')?{content:stored}:(stored=args.content,{saved:true});
  const drawing=await openDrawing(rpc,'commented.excalidraw.md');
  assert.equal(drawing.readOnly,false);
  await saveDrawing(rpc,drawing,{...drawing.scene,elements:[{id:'text1234',type:'text',rawText:'文字',text:'文字'}]});
  assert.match(stored,/文字 \^text1234\n\n%%\n## Drawing/);
  const reopened=await openDrawing(rpc,'commented.excalidraw.md');
  assert.equal(reopened.readOnly,false);
});

test('Markdown external element links use original link index and preserve identity', async () => {
  let stored='---\nexcalidraw-plugin: parsed\n---\n\n# Excalidraw Data\n\n## Text Elements\n\n%%\n## Drawing\n```json\n{"type":"excalidraw","elements":[],"appState":{},"files":{}}\n```\n%%\n';
  const rpc=async(method,args)=>method.endsWith('read')?{content:stored}:(stored=args.content,{saved:true});
  const drawing=await openDrawing(rpc,'links.excalidraw.md');
  await saveDrawing(rpc,drawing,{...drawing.scene,elements:[{id:'rect-long',type:'rectangle',link:'https://example.com'}]});
  const entry=stored.match(/## Element Links\n([a-zA-Z0-9]{8}): https:\/\/example\.com/); assert.ok(entry);
  const reopened=await openDrawing(rpc,'links.excalidraw.md');
  assert.equal(reopened.readOnly,false); assert.equal(reopened.scene.elements[0].id,entry[1]);
});

test('Markdown imported images become original-style workspace attachments and reopen', async () => {
  let stored='---\nexcalidraw-plugin: parsed\n---\n\n# Excalidraw Data\n\n## Text Elements\n\n%%\n## Drawing\n```json\n{"type":"excalidraw","elements":[],"appState":{},"files":{}}\n```\n%%\n';
  const dataURL='data:image/png;base64,iVBORw0KGgo=';
  const assetPath='.excalidraw-assets/'+'a'.repeat(64)+'.png'; const assets=new Map();
  const rpc=async(method,args)=>{
    if(method==='excalidraw.file.read')return {content:stored};
    if(method==='excalidraw.file.write'){stored=args.content;return {saved:true}}
    if(method==='excalidraw.asset.put'){assert.equal(args.dataURL,dataURL);assets.set(assetPath,dataURL);return {path:assetPath}}
    if(method==='excalidraw.asset.read')return {dataURL:assets.get(args.path)};
    throw Error(method);
  };
  const drawing=await openDrawing(rpc,'images.excalidraw.md');
  const scene={...drawing.scene,elements:[{id:'img',type:'image',fileId:'file123',isDeleted:false}],files:{file123:{id:'file123',mimeType:'image/png',dataURL,created:123}}};
  await saveDrawing(rpc,drawing,scene);
  assert.ok(stored.includes('## Embedded Files\nfile123: [['+assetPath+']]'));
  const reopened=await openDrawing(rpc,'images.excalidraw.md');
  assert.equal(reopened.readOnly,false); assert.equal(reopened.scene.files.file123.dataURL,dataURL);
});

test('unreferenced image data is never discarded by Markdown save', async () => {
  const drawing={path:'new.excalidraw.md',original:null,markdown:true,scene:{type:'excalidraw',elements:[],appState:{},files:{}}};
  let wrote=false;const rpc=async()=>{wrote=true;return {saved:true}};
  await assert.rejects(saveDrawing(rpc,drawing,{...drawing.scene,files:{orphan:{id:'orphan',dataURL:'data:image/png;base64,AAAA'}}}),/附件/);
  assert.equal(wrote,false);
});

test('ambiguous duplicate attachment references remain read-only', async () => {
  const p='.excalidraw-assets/'+'a'.repeat(64)+'.png';
  const scene={type:'excalidraw',elements:[{id:'x',type:'image',fileId:'a'},{id:'y',type:'image',fileId:'b'}],appState:{},files:{}};
  const original=`---\nexcalidraw-plugin: parsed\n---\n\n# Excalidraw Data\n\n## Text Elements\n\n## Embedded Files\na: [[${p}]]\n\na: [[${p}]]\n\n%%\n## Drawing\n\`\`\`json\n${JSON.stringify(scene)}\n\`\`\`\n%%\n`;
  const drawing=await openDrawing(async(method)=>method.endsWith('read')?{content:original}:{dataURL:'data:image/png;base64,AAAA'},'bad.excalidraw.md');
  assert.equal(drawing.readOnly,true);
});

test('original workspace image references remain links and detect external image changes', async () => {
  let stored='---\nexcalidraw-plugin: parsed\n---\n\n# Excalidraw Data\n\n## Text Elements\n\n## Embedded Files\nimage001: [[图片.png]]\n\n%%\n## Drawing\n```json\n{"type":"excalidraw","elements":[{"id":"image","type":"image","fileId":"image001"}],"appState":{},"files":{}}\n```\n%%\n';
  let image='data:image/png;base64,AAAA';let writes=0;
  const rpc=async(method,args)=>{
    if(method==='excalidraw.file.read')return {content:stored};
    if(method==='excalidraw.asset.read'){assert.equal(args.drawingPath,'notes/drawing.excalidraw.md');return {dataURL:image,path:'notes/图片.png'}}
    if(method==='excalidraw.asset.put')throw Error('existing asset must not be copied');
    if(method==='excalidraw.file.write'){writes++;stored=args.content;return {saved:true}}
    throw Error(method);
  };
  const drawing=await openDrawing(rpc,'notes/drawing.excalidraw.md');
  assert.equal(drawing.readOnly,false);assert.equal(drawing.scene.files.image001.dataURL,image);
  await saveDrawing(rpc,drawing,drawing.scene);
  assert.match(stored,/image001: \[\[图片\.png\]\]/);assert.equal(writes,1);
  image='data:image/png;base64,AQID';
  await assert.rejects(saveDrawing(rpc,drawing,drawing.scene),/附件.*更改/);
  assert.equal(writes,1);
});

test('original internal element link keeps its index and opens through the host', async () => {
  const { followInternalLink }=await import('../plugins/excalidraw/ui/src/document.mjs');
  let stored='---\nexcalidraw-plugin: parsed\n---\n\n# Excalidraw Data\n\n## Text Elements\n\n%%\n## Drawing\n```json\n{"type":"excalidraw","elements":[],"appState":{},"files":{}}\n```\n%%\n';
  const calls=[];const rpc=async(method,args)=>{calls.push([method,args]);if(method.endsWith('read'))return {content:stored};if(method.endsWith('write')){stored=args.content;return {saved:true}};return {path:'E:/work/notes/文档.md'}};
  const drawing=await openDrawing(rpc,'notes/drawing.excalidraw.md');
  await saveDrawing(rpc,drawing,{...drawing.scene,elements:[{id:'longid123456',type:'rectangle',link:'[[文档.md|说明]]'}]});
  assert.match(stored,/\[\[文档\.md\|说明\]\]/);
  const reopened=await openDrawing(rpc,'notes/drawing.excalidraw.md'); assert.equal(reopened.readOnly,false);
  const opened=[];await followInternalLink(rpc,path=>opened.push(path),drawing.path,'[[文档.md|说明]]');
  assert.deepEqual(opened,['E:/work/notes/文档.md']);
  assert.equal(calls.at(-1)[1].drawingPath,'notes/drawing.excalidraw.md');
});
