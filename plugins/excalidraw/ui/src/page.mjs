// user:“该修就修，不用停下”+(使用原版插件依赖的定制 Excalidraw 画布，宿主负责页面生命周期)。
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createExcalidrawRuntime } from 'upstream-excalidraw-runtime';
let ExcalidrawLib;
// user:“该修就修，不用停下”+(按上游画布的宿主协议接入默认设置，并明确提示尚未接入的功能)。
function configureCanvasHost(lib) {
  const labels = {ABOUT_LIBRARIES:'如何加载素材库', INSERT_CARD:'插入背景笔记卡片', COMP_IMG:'图片 & 文件', COMP_IMG_FROM_SYSTEM:'从系统导入', COMP_IMG_ANY_FILE:'工作区文件', COMP_IMG_LaTeX:'LaTeX 公式', COMP_FRAME:'画框操作', COMP_FRAME_HINT:'切换标记画框'};
  const unsupported = action => { window.dispatchEvent(new CustomEvent('sunday-excalidraw-unsupported', {detail: action})); };
  return lib.configureObsidianExcalidrawHost({
    protocolVersion:lib.OBSIDIAN_EXCALIDRAW_HOST_PROTOCOL_VERSION,
    isDoubleTapEraserEnabled:()=>true, getZoomToFitMaxLevel:()=>2, isPenModeCrosshairVisible:()=>true,
    isSingleFingerPanningEnabled:()=>true, isDoubleClickTextEditingDisabled:()=>false,
    getZoomStep:()=>0.05, getZoomMin:()=>0.1, getZoomMax:()=>30, isContextMenuDisabled:()=>false,
    shouldSyncElementLinkWithText:()=>false,
    loadFontFromFile:async()=>{ unsupported('自定义字体'); return undefined; },
    getMermaid:async()=>({loaded:true,api:import(/* @vite-ignore */ new URL('./mermaid.mjs', import.meta.url).href)}),
    runAction:action=>unsupported(action), getLabel:key=>labels[key] || key,
    attachInlineLinkSuggester(input) {
      const changed=()=>{if (input.value.includes('[[')) unsupported('工作区链接补全');};
      input.addEventListener('input',changed);
      return {isBlockingKeys:()=>false,close:()=>input.removeEventListener('input',changed)};
    },
  });
}

import upstreamCSS from 'upstream-excalidraw-css';
import { followInternalLink, openDrawing, saveDrawing } from './document.mjs';

const h = React.createElement;
// user:“该修就修，不用停下”+(画布字体来自随插件发布的本地资源，多页面共用时保留并恢复之前的路径)。
let assetUsers = 0, previousAssetPath, fallbackSavePicker;
function createDownloadPicker() {
  return async options => {
    const parts = [];
    return { kind: 'file', name: options?.suggestedName || 'drawing', async createWritable() {
      return { async write(value) { parts.push(value); }, async close() {
        const url = URL.createObjectURL(new Blob(parts));
        const a = document.createElement('a'); a.href = url; a.download = options?.suggestedName || 'drawing'; document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      } };
    } };
  };
}
function acquireAssets(base) {
  if (assetUsers++ === 0) {
    previousAssetPath = window.EXCALIDRAW_ASSET_PATH;
    if (typeof window.showSaveFilePicker !== 'function') { fallbackSavePicker = createDownloadPicker(); window.showSaveFilePicker = fallbackSavePicker; }
  }
  window.EXCALIDRAW_ASSET_PATH = base;
  return () => { if (--assetUsers === 0) {
    if (window.EXCALIDRAW_ASSET_PATH === base) window.EXCALIDRAW_ASSET_PATH = previousAssetPath;
    if (fallbackSavePicker && window.showSaveFilePicker === fallbackSavePicker) { delete window.showSaveFilePicker; fallbackSavePicker = null; }
  } };
}
function Editor({ context }) {
  const { Excalidraw } = ExcalidrawLib;
  const [path, setPath] = useState(context.filePath || 'drawing.excalidraw');
  // user:“FileNotFoundError: [Errno 2] No such file or directory”+(首次进入即提供可保存的新画图，原文件和草稿仍受冲突保护)。
  const [drawing, setDrawing] = useState(() => {
    if (context.filePath) return null;
    const name = 'drawing.excalidraw';
    try {
      const draft = JSON.parse(localStorage.getItem(`sunday:excalidraw:draft:${JSON.stringify([context.workRoot || '', name])}`) || 'null');
      if (draft && draft.original !== null) return null;
      return {path:name, original:null, scene:draft ? JSON.parse(draft.json) : {type:'excalidraw',version:2,source:'https://excalidraw.com',elements:[],appState:{},files:{}}, markdown:false, recovered:!!draft};
    } catch { return null; }
  });
  const [conflictDraft, setConflictDraft] = useState(null);
  const [key, setKey] = useState(0);
  const [message, setMessage] = useState(drawing ? '新画图尚未保存' : '请输入工作区内的画图路径后打开，或点击新建。');
  const api = useRef(null);
  const pendingMessage = useRef(null);
  // user:“该修就修，不用停下”+(自动保存沿用原版桌面默认间隔，关闭时仍保留草稿)。
  const autosaveMs = context.settings?.autosaveIntervalDesktop ?? 60000;
  const baseline = useRef(null), pending = useRef(null), timer = useRef(null);
  const queue = useRef(Promise.resolve());
  // user:“该修就修，不用停下”+(关闭页面时保留尚未写入文件的草稿，外部修改后不自动覆盖)。
  const draftKey = name => `sunday:excalidraw:draft:${JSON.stringify([context.workRoot || '', name])}`;
  const readDraft = name => { try { return JSON.parse(localStorage.getItem(draftKey(name)) || 'null'); } catch { return null; } };
  const writeDraft = (target, current) => {
    try { localStorage.setItem(draftKey(target.path), JSON.stringify({ original: target.original, json: current.json })); }
    catch { setMessage('草稿暂时无法缓存，请尽快保存'); }
  };
  useEffect(() => {
    const unsupported = event => setMessage(`${event.detail}暂未接入`);
    window.addEventListener('sunday-excalidraw-unsupported', unsupported);
    return () => { clearTimeout(timer.current); window.removeEventListener('sunday-excalidraw-unsupported', unsupported); };
  }, []);
  function clearSceneTracking() { clearTimeout(timer.current); pending.current = null; baseline.current = null; }
  function flush(target, automatic = false) {
    clearTimeout(timer.current);
    const task = queue.current.catch(() => {}).then(async () => {
      if (!target || !pending.current) return;
      const current = pending.current;
      await saveDrawing(context.rpc, target, current.scene);
      baseline.current = current.json;
      if (pending.current === current) {
        pending.current = null;
        const draft = readDraft(target.path);
        if (draft?.json === current.json) { try { localStorage.removeItem(draftKey(target.path)); } catch {} }
      } else {
        // user:“该修就修，不用停下”+(写入期间产生的新草稿以刚写入的版本为基础，关闭后仍能恢复)。
        writeDraft(target, pending.current);
      }
      if (!pending.current && target.sourceDraft) {
        const source = readDraft(target.sourceDraft.path);
        if (source?.json === target.sourceDraft.json) { try { localStorage.removeItem(draftKey(target.sourceDraft.path)); } catch {} }
        target.sourceDraft = null;
      }
      setMessage(automatic ? '已自动保存' : '已保存');
    });
    queue.current = task;
    return task;
  }
  const onChange = useCallback((elements, appState, files) => {
    if (!drawing || drawing.readOnly) return;
    const json = ExcalidrawLib.serializeAsJSON(elements, appState, files, 'local');
    if (baseline.current === null) {
      baseline.current = json;
      if (drawing.recovered) {
        drawing.recovered = false;
        pending.current = {json, scene: JSON.parse(json)};
        writeDraft(drawing, pending.current);
        timer.current = setTimeout(() => { flush(drawing, true).catch(error => setMessage(String(error.message || error))); }, autosaveMs);
      }
      return;
    }
    if (json === baseline.current && !pending.current) return;
    pending.current = { json, scene: JSON.parse(json) };
    writeDraft(drawing, pending.current);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { flush(drawing, true).catch(error => setMessage(String(error.message || error))); }, autosaveMs);
  }, [drawing, context]);
  const [ready, setReady] = useState(false);
  const onApi = useCallback(value => {
    api.current = value; setReady(!!value);
    if (value && pendingMessage.current) { setMessage(pendingMessage.current); pendingMessage.current = null; }
  }, []);
  async function open() {
    try { await flush(drawing); const next = await openDrawing(context.rpc, path); const draft = readDraft(path);
      if (draft && !next.readOnly) {
        if (draft.original !== next.original) { setConflictDraft({path, ...draft}); throw new Error('原文件已更改，草稿仍保留；请先核对文件'); }
        next.scene = JSON.parse(draft.json); next.recovered = true;
      }
      clearSceneTracking(); setConflictDraft(null); pendingMessage.current = next.readOnly ? '已打开（原版 Markdown 暂只读）' : '已打开'; setReady(false); setDrawing(next); setKey(k => k + 1); setMessage('正在打开画图'); }
    catch (e) { setMessage(String(e.message || e)); }
  }
  async function create() {
    try { await flush(drawing); } catch (e) { setMessage(String(e.message || e)); return; }
    const draft = readDraft(path);
    if (draft && draft.original !== null) { setMessage('此文件有未保存草稿，请先打开原文件'); return; }
    let scene;
    try { scene = draft ? JSON.parse(draft.json) : { type: 'excalidraw', version: 2, source: 'https://excalidraw.com', elements: [], appState: {}, files: {} }; }
    catch { setMessage('草稿无法读取，原数据仍保留'); return; }
    clearSceneTracking(); pendingMessage.current = '新画图尚未保存'; setReady(false);
    setDrawing({ path, original: null, scene, markdown: /\.md$/i.test(path), recovered: !!draft });
    setKey(k => k + 1); setMessage('正在新建画图');
  }
  // user:“该修就修，不用停下”+(由宿主文件树打开时直接载入对应画图)。
  useEffect(() => { if (context.filePath) void open(); }, []);
  async function recoverCopy() {
    if (!conflictDraft) return;
    try {
      await flush(drawing);
      const scene = JSON.parse(conflictDraft.json);
      const recoveredPath = `${conflictDraft.path}.recovered.excalidraw`;
      clearSceneTracking(); setPath(recoveredPath); setConflictDraft(null);
      pendingMessage.current = '正在恢复草稿'; setReady(false);
      setDrawing({path:recoveredPath,original:null,scene,recovered:true,sourceDraft:conflictDraft});
      setKey(k=>k+1); setMessage('正在恢复草稿');
    } catch (error) { setMessage(String(error.message || error)); }
  }
  function onLinkOpen(element, event) {
    if (!element.link?.startsWith('[[')) return;
    event.preventDefault();
    if (typeof context.openFile !== 'function') { setMessage('宿主尚未提供文件导航'); return; }
    void followInternalLink(context.rpc, context.openFile, drawing?.path || '', element.link)
      .catch(error => setMessage(String(error.message || error)));
  }
  async function save() {
    try {
      if (!drawing || !api.current) throw new Error('先新建或打开画图');
      setMessage('正在保存');
      const json = ExcalidrawLib.serializeAsJSON(api.current.getSceneElementsIncludingDeleted(), api.current.getAppState(), api.current.getFiles(), 'local');
      const scene = JSON.parse(json); pending.current = { json, scene }; writeDraft(drawing, pending.current);
      await flush(drawing);
    } catch (e) { setMessage(String(e.message || e)); }
  }
  return h('div', { className: 'sunday-excalidraw' },
    h('div', { className: 'sunday-excalidraw-toolbar' },
      h('input', { 'aria-label': '工作区文件路径', value: path, onChange: e => setPath(e.target.value) }),
      h('button', { onClick: create }, '新建'), h('button', { onClick: open }, '打开'), h('button', { onClick: save, disabled: !ready }, '保存'), conflictDraft && h('button', {onClick:recoverCopy}, '恢复为副本'), h('span', { role: 'status' }, message)),
    h('div', { className: 'sunday-excalidraw-canvas' }, h(Excalidraw, { key, onExcalidrawAPI: onApi, initialData: drawing?.scene, onChange, onLinkOpen, viewModeEnabled: !!drawing?.readOnly, langCode: 'zh-CN' })));
}
export function mount(root, context) {
  const base = new URL('./', import.meta.url).href;
  const releaseAssets = acquireAssets(base);
  let removeStyle, reactRoot;
  try {
    if (!ExcalidrawLib) { const runtime = createExcalidrawRuntime(); configureCanvasHost(runtime); ExcalidrawLib = runtime; }
    const css = upstreamCSS.replaceAll('url("./fonts/', `url("${base}fonts/`);
    removeStyle = context.addStyle(css + '\n.sunday-excalidraw{height:100%;min-height:400px;display:flex;flex-direction:column}.sunday-excalidraw-toolbar{display:flex;gap:var(--space-2,8px);align-items:center;padding:var(--space-1,4px);flex-wrap:wrap}.sunday-excalidraw-toolbar input{min-width:12rem;min-height:32px;padding:0 var(--space-2,8px);border:1px solid var(--theme-main-border,#777);border-radius:var(--radius-sm,6px);background:var(--theme-composer-background,#25262b);color:var(--theme-composer-text,#fff)}.sunday-excalidraw-toolbar button{min-height:32px;padding:0 var(--space-3,12px);border:1px solid color-mix(in srgb,var(--theme-control-text,#fff) 20%,transparent);border-radius:var(--radius-sm,6px);background:var(--theme-control-background,#34363c);color:var(--theme-control-text,#fff);cursor:pointer}.sunday-excalidraw-toolbar button:enabled:hover{background:linear-gradient(color-mix(in srgb,var(--theme-control-text,#fff) var(--alpha-hover,8%),transparent),color-mix(in srgb,var(--theme-control-text,#fff) var(--alpha-hover,8%),transparent)),var(--theme-control-background,#34363c)}.sunday-excalidraw-toolbar button:enabled:active{background:linear-gradient(color-mix(in srgb,var(--theme-control-text,#fff) var(--alpha-active,12%),transparent),color-mix(in srgb,var(--theme-control-text,#fff) var(--alpha-active,12%),transparent)),var(--theme-control-background,#34363c)}.sunday-excalidraw-toolbar button:disabled{opacity:.45;cursor:default}.sunday-excalidraw-toolbar [role=status]{font-size:13px;color:color-mix(in srgb,var(--theme-main-text,#fff) 65%,transparent)}.sunday-excalidraw-canvas{flex:1;min-height:0}.excalidraw[data-radix-portal]{position:relative;z-index:1000}.excalidraw [data-radix-popper-content-wrapper]{z-index:10000!important}.sunday-excalidraw .excalidraw{--editor-container-padding:1rem}.sunday-excalidraw .excalidraw .App-toolbar .Stack_horizontal{height:2.5rem;align-items:center}.sunday-excalidraw .excalidraw .App-toolbar .ToolIcon{height:2rem}');
    reactRoot = createRoot(root); reactRoot.render(h(Editor, { context }));
  } catch (error) {
    // user:“如图，我不清楚这是不是你写出来的界面的设计的样子”+(初始化失败时清理已占用的资源并让宿主显示错误)。
    reactRoot?.unmount(); removeStyle?.(); releaseAssets(); throw error;
  }
  return () => { reactRoot.unmount(); removeStyle(); releaseAssets(); };
}
