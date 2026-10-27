// user:“该修就修，不用停下”+(复用上游解析、压缩及文本索引生成；未适配的链接或嵌入不覆盖原文)。
import { FRONTMATTER, getJSON, compress, getMarkdownDrawingSection } from './upstream-markdown.mjs';
import { generateMDBase, updateElementIdsInScene } from './upstream-markdown-writer.mjs';
const block = /(\n##? Drawing\n[^`]*```(compressed-json|json)\n)([\s\S]*?)(\n```\n)/m;
const textSection = /(^##? Text Elements[ \t]*\n)([\s\S]*?)(?=^%%[ \t]*\n##? Drawing\n|^##? Drawing\n)/m;
const simpleTypes = new Set(['rectangle','ellipse','diamond','arrow','line','freedraw','frame','magicframe','text','image']);
const isSupportedLink = link => /^https?:\/\/[^\s]+$/.test(link) || /^\[\[[^\]#\r\n]+\]\]$/.test(link);
const rawText = element => element.rawText || element.originalText || element.text || '';
function simpleScene(scene) {
  return scene.elements.every(element => simpleTypes.has(element.type) && (!element.link || isSupportedLink(element.link)) && (element.type === 'image' ? typeof element.fileId === 'string' : !element.fileId) &&
    (element.type !== 'text' || (typeof rawText(element) === 'string' && !/\[\[|\]\(|\^.{8}\s*$/m.test(rawText(element)))));
}
function simpleMarkdown(content, scene) {
  if (!block.test(content) || !simpleScene(scene)) return false;
  const section = content.match(textSection); if (!section) return false;
  const assetParts = section[2].split(/^## Embedded Files[ \t]*\n/m);
  if (assetParts.length > 2) return false;
  const assetText = assetParts[1] || '';
  const assetPattern = /^([a-zA-Z0-9_-]+): \[\[([^\]\r\n#|]+\.(?:png|jpg|jpeg|gif|webp|svg))\]\]\n\n/gim;
  const assets = [...assetText.matchAll(assetPattern)];
  if (assetText.replace(assetPattern, '').trim()) return false;
  const ids = new Set(scene.elements.filter(e=>e.type==='image'&&!e.isDeleted).map(e=>e.fileId));
  if (assets.length !== ids.size || new Set(assets.map(entry=>entry[1])).size !== ids.size || !assets.every(entry=>ids.has(entry[1]))) return false;
  const pieces = assetParts[0].split(/^## Element Links[ \t]*\n/m);
  if (pieces.length > 2) return false;
  const body = pieces[0];
  const links = pieces[1] || '';
  const linkPattern = /^([a-zA-Z0-9]{8}): (https?:\/\/[^\s]+|\[\[[^\]#\r\n]+\]\])\n\n/gm;
  const linkEntries = [...links.matchAll(linkPattern)];
  if (links.replace(linkPattern, '').trim()) return false;
  const linked = scene.elements.filter(e => e.link && !e.isDeleted);
  if (linkEntries.length !== linked.length || new Set(linkEntries.map(entry=>entry[1])).size !== linked.length || !linkEntries.every(entry => linked.some(e => e.id === entry[1] && e.link === entry[2]))) return false;
  const entries = [...body.matchAll(/([\s\S]*?) \^([a-zA-Z0-9]{8})\n\n/g)];
  const remaining = body.replace(/([\s\S]*?) \^([a-zA-Z0-9]{8})\n\n/g,'').trim();
  if (remaining) return false;
  const texts = scene.elements.filter(e => e.type === 'text' && !e.isDeleted);
  if (entries.length !== texts.length || new Set(entries.map(entry=>entry[2])).size !== texts.length) return false;
  return entries.every((entry) => { const element = texts.find(e => e.id === entry[2]); return element && rawText(element) === entry[1].replace(/^\n+/, ''); });
}
function nextId(used) {
  const alphabet = '1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
  for (;;) { const bytes = crypto.getRandomValues(new Uint8Array(8)); const id = [...bytes].map(x => alphabet[x % alphabet.length]).join(''); if (!used.has(id)) { used.add(id); return id; } }
}
function prepareMarkdownScene(drawing, scene) {
  const copy = JSON.parse(JSON.stringify(scene));
  if (!simpleScene(copy)) throw new Error('含工作区链接或嵌入的 Markdown 画图暂不支持保存');
  const used = new Set(copy.elements.map(e=>e.id)); drawing.idMap ||= new Map();
  for (const element of copy.elements) if ((element.type === 'text' || element.link) && !element.isDeleted && !/^[a-zA-Z0-9]{8}$/.test(element.id)) {
    if (element.containerId && !copy.elements.some(e=>e.id===element.containerId)) throw new Error('文本容器不存在，不能保存');
    const old = element.id; const id = drawing.idMap.get(old) || nextId(used); drawing.idMap.set(old,id);
    updateElementIdsInScene(copy,element,id);
  }
  return copy;
}
export async function openDrawing(rpc, path) {
  const result = await rpc('excalidraw.file.read', { path });
  // user:“FileNotFoundError: [Errno 2] No such file or directory”+(告诉用户如何处理缺失文件)。
  if (result?.missing || result?.content === undefined) throw new Error('画图文件不存在，请检查路径或点击新建');
  const content = result.content;
  if (typeof content !== 'string') throw new Error('画图文件读取失败');
  const markdown = /\.md$/i.test(path);
  const scene = JSON.parse(markdown ? getJSON(content).scene : content);
  if (scene.type !== 'excalidraw' || !Array.isArray(scene.elements)) throw new Error('这不是有效的 Excalidraw 文件');
  const readOnly = markdown && !simpleMarkdown(content, scene);
  const assetReferences = new Map();
  if (markdown && !readOnly) {
    scene.files ||= {};
    const section = content.match(textSection)?.[2] || '';
    const assetPattern = /^([a-zA-Z0-9_-]+): \[\[([^\]\r\n#|]+\.(?:png|jpg|jpeg|gif|webp|svg))\]\]\n\n/gim;
    for (const entry of section.matchAll(assetPattern)) {
      const asset = await rpc('excalidraw.asset.read',{path:entry[2], drawingPath:path});
      if (!asset?.dataURL?.startsWith('data:image/')) throw new Error('画图附件读取失败');
      scene.files[entry[1]] = {id:entry[1],dataURL:asset.dataURL,mimeType:asset.dataURL.slice(5,asset.dataURL.indexOf(';')),created:Date.now()};
      assetReferences.set(entry[1],{link:entry[2],dataURL:asset.dataURL});
    }
  }
  return { path, original: content, scene, markdown, readOnly, assetReferences };
}

export async function saveDrawing(rpc, drawing, scene) {
  if (drawing.readOnly || (/\.md$/i.test(drawing.path) && !drawing.markdown)) throw new Error('此原版 Markdown 画图暂不支持保存');
  let next = { ...drawing.scene, ...scene, type: 'excalidraw', version: 2 };
  let content;
  if (drawing.markdown) {
    next = prepareMarkdownScene(drawing, next);
    const embedded = new Map(), nextAssetReferences = new Map();
    const activeFiles = new Set(next.elements.filter(e=>e.type==='image'&&!e.isDeleted).map(e=>e.fileId));
    if (Object.keys(next.files || {}).some(id=>!activeFiles.has(id))) throw new Error('存在未关联的附件数据，未保存画图');
    for (const id of activeFiles) {
      const dataURL = next.files?.[id]?.dataURL;
      if (!dataURL) throw new Error('图片附件数据缺失，未保存画图');
      const previous = drawing.assetReferences?.get(id);
      let link;
      if (previous && previous.dataURL === dataURL) {
        const current = await rpc('excalidraw.asset.read',{path:previous.link,drawingPath:drawing.path});
        if (current?.dataURL !== previous.dataURL) throw new Error('图片附件已更改，未保存画图');
        link = previous.link;
      } else {
        const saved = await rpc('excalidraw.asset.put',{dataURL});
        if (!/^\.excalidraw-assets\/[0-9a-f]{64}\.(png|jpg|gif|webp|svg)$/.test(saved?.path || '')) throw new Error('图片附件保存失败');
        link = saved.path;
      }
      embedded.set(id,{linkParts:{original:link}});
      nextAssetReferences.set(id,{link,dataURL});
    }
    const textElements = new Map(next.elements.filter(e=>e.type==='text'&&!e.isDeleted).map(e=>[e.id,{raw:rawText(e)}]));
    const elementLinks = new Map(next.elements.filter(e=>e.type!=='text' && e.link && !e.isDeleted).map(e=>[e.id,e.link]));
    const state={scene:{...next,files:{}},plugin:{settings:{syncElementLinkWithText:false,addDummyTextElement:false}},textElementCommentedOut:false,textElements,elementLinks,equations:new Map(),files:embedded,markdownImages:new Map()};
    const generated = generateMDBase.call(state, []);
    next._pendingAssetReferences = nextAssetReferences;
    const textBody = generated.outString.split('## Text Elements\n')[1];
    if (drawing.original === null) {
      content = FRONTMATTER + generated.outString + '%%\n' + getMarkdownDrawingSection(generated.sceneJSONstring, true);
    } else {
      content = drawing.original.replace(textSection, (_, header, body) => header + textBody);
      content = content.replace(block, (_, prefix, kind, body, suffix) => prefix + (kind === 'compressed-json' ? compress(generated.sceneJSONstring) : generated.sceneJSONstring) + suffix);
    }
  } else content = JSON.stringify(next, null, 2);
  const result = await rpc('excalidraw.file.write', { path: drawing.path, content, original: drawing.original });
  if (!result?.saved) throw new Error(result?.error || '保存失败');
  drawing.original = content;
  if (drawing.markdown) { drawing.assetReferences = next._pendingAssetReferences; delete next._pendingAssetReferences; }
  drawing.scene = next;
}

// user:“该修就修，不用停下”+(原版内部链接经宿主解析，沿用当前项目打开对应文件)。
export async function followInternalLink(rpc, openFile, drawingPath, link) {
  const match = /^\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]$/.exec(link);
  if (!match) throw new Error('此工作区链接暂不支持');
  const result = await rpc('excalidraw.link.resolve',{path:match[1],drawingPath});
  if (typeof result?.path !== 'string' || !result.path) throw new Error('找不到链接文件');
  openFile(result.path);
}
