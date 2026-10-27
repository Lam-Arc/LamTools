// user:“不需要 lamtools 重写 就移植原版就行”+(原版 React 组件和 CSS 完整执行，只适配加载器、HTTP 与宿主生命周期)。
import * as React from 'react';
import { createRoot } from 'react-dom/client';
import { register } from 'dsh-original-client';

const VERSION = '2.3.0';
export function mount(root, context) { return mountOriginal(root, context, 'settings.section'); }
export function mountWatched(root, context) { return mountOriginal(root, context, 'conversation.view'); }

function mountOriginal(root, context, slot) {
  const document = root.ownerDocument, browser = document.defaultView;
  const controller = new AbortController(), cleanups = [], components = new Map();
  const host = document.createElement('div');
  host.dataset.biliOriginal = '2.2.2';
  // DSH 原版的主题别名映射到当前宿主；不改原版选择器、布局和控件样式。
  host.style.cssText = `color:var(--theme-main-text,#f2efeb);font-family:var(--font-sans,system-ui,sans-serif);font-size:13px;
    --dsw-alias-label-primary:var(--theme-main-text,#f2efeb);--dsw-alias-label-secondary:color-mix(in srgb,var(--theme-main-text,#f2efeb) 80%,transparent);
    --dsw-alias-label-tertiary:color-mix(in srgb,var(--theme-main-text,#f2efeb) 65%,transparent);
    --dsw-alias-bg-layer-1:var(--theme-main-solid,#262625);--dsw-alias-bg-layer-2:var(--theme-main-subtle-background,rgba(127,127,127,.08));
    --dsw-alias-bg-layer-3:var(--theme-main-border,rgba(127,127,127,.22));--dsw-alias-bg-layer-4:var(--theme-composer-background,rgba(127,127,127,.12));
    --dsw-alias-interactive-bg-hover:color-mix(in srgb,var(--theme-main-text,#f2efeb) 8%,transparent);`;
  root.append(host);
  let disposed = false;
  const rpc = async (name, args = {}) => {
    if (disposed || controller.signal.aborted) throw new DOMException('页面已关闭', 'AbortError');
    const result = await context.rpc('bili-scroll.' + name, args);
    if (disposed) throw new DOMException('页面已关闭', 'AbortError');
    return result;
  };
  const request = async (path, body) => {
    const url = new URL(path, 'http://plugin.local'), name = url.pathname.replace('/api/bili-duty', '');
    const args = Object.fromEntries(url.searchParams);
    switch (name) {
      case '/status': {
        const [status, config, mainLog, asrLog] = await Promise.all([rpc('status'), rpc('config_get'), rpc('install_log'), rpc('install_log', { kind: 'asr' })]);
        return { ...status, ...status.env, config: config.config, version: VERSION,
          installTail: (mainLog.lines || []).join('\n'), asrTail: (asrLog.lines || []).join('\n') };
      }
      case '/config': return rpc('config_update', { patch: body });
      case '/watched': {
        const data = await rpc('watched', { ...args, offset: Number(args.offset || 0), limit: Number(args.limit || 30) });
        return { ...data, rows: (data.items || []).map(item => ({ ...item, url: item.url || 'https://www.bilibili.com/video/' + item.bvid,
          picked: item.picked ?? item.state === 'picked', up: item.up || '', commented: item.commented ?? item.state === 'commented' })) };
      }
      case '/diagnose': { const data = await rpc('diagnose'); return { ok: true, text: JSON.stringify(data, null, 2) }; }
      case '/selfcheck': {
        const data = await rpc('selfcheck'); return { ...data, items: Object.entries(data.checks || {}).map(([name, ok]) => ({ name, ok, detail: ok ? '已就绪' : '未就绪', fix: '检查环境与配置后重试' })) };
      }
      case '/verify': { const data = await rpc('verify'); return { ...data, checked: data.items || [] }; }
      case '/fav-today': { const data = await rpc('fav_add_today'); return { ...data, added: data.added?.length || 0, total: (data.added?.length || 0) + (data.failed?.length || 0), failures: data.failed || [] }; }
      case '/login/start': { const data = await rpc('login_start'); return { ...data, qr: data.png_data }; }
      case '/login/poll': return rpc('login_poll', body);
      case '/open': {
        if (body.what === 'url') { const url = new URL(body.u); if (!['http:', 'https:'].includes(url.protocol)) throw new Error('链接格式不支持'); browser.open(url.href, '_blank', 'noopener,noreferrer'); return { ok: true, opened: url.href }; }
        const data = await rpc('open_home', { what: body.what }); return { ...data, opened: data.path, dir: data.path };
      }
      case '/update': {
        const data = await rpc('update_check'); return { ...data, latest: String(data.upstream_tag || '').replace(/^v/, ''), current: '2.2.2', hasNew: String(data.upstream_tag || '').replace(/^v/, '').localeCompare('2.2.2', undefined, { numeric: true }) > 0, source: 'github' };
      }
      case '/upgrade': throw new Error('DSH 原版安装包不能直接覆盖此宿主适配；请在宿主插件页更新兼容包');
      default: {
        const method = { '/report': 'report_read', '/fav-folders': 'fav_folders', '/check': 'check', '/install-asr': 'install_asr', '/install': 'setup', '/run': 'run_round' }[name];
        if (!method) throw new Error('不支持的原版接口：' + name);
        return rpc(method, body || args);
      }
    }
  };
  const fetch = async (path, init = {}) => {
    try { return new Response(JSON.stringify(await request(path, init.body ? JSON.parse(init.body) : {})), { status: 200, headers: { 'Content-Type': 'application/json' } }); }
    catch (error) { if (error.name === 'AbortError') throw error; return new Response(JSON.stringify({ ok: false, error: error.message }), { status: 500 }); }
  };
  function Cover(props) {
    const [src, setSrc] = React.useState('');
    React.useEffect(() => {
      let active = true;
      const bvid = new URL(props.src, 'http://plugin.local').searchParams.get('bv');
      rpc('cover_data', { bvid }).then(data => { if (active) setSrc(data.data_url || ''); }).catch(() => {});
      return () => { active = false; };
    }, [props.src]);
    return React.createElement('img', { ...props, src: src || undefined });
  }
  const react = { ...React, createElement(type, props, ...children) {
    return React.createElement(type === 'img' && props?.src?.startsWith('/api/bili-duty/cover?') ? Cover : type, props, ...children);
  } };
  const localDocument = new Proxy(document, { get(target, key) {
    if (key === 'createElement') return (...args) => { const node = target.createElement(...args); if (args[0] === 'style') node.nonce = target.querySelector('style[nonce]')?.nonce || ''; return node; };
    const value = Reflect.get(target, key, target); return typeof value === 'function' ? value.bind(target) : value;
  } });
  const slots = { inject(_name, callback) { callback(); }, register(spec, component) { components.set(spec.name, component); } };
  register({ __ModuleLoader__: { load(definition) {
    definition.factory(name => { if (name === 'react') return react; throw new Error('未知原版依赖：' + name); }).apply({
      get: () => slots, slots, effect(callback) { const cleanup = callback(); if (typeof cleanup === 'function') cleanups.push(cleanup); },
    });
  } } }, localDocument, fetch);
  const view = createRoot(host); view.render(components.get(slot)());
  function dispose() { if (disposed) return; disposed = true; controller.abort(); view.unmount(); cleanups.splice(0).reverse().forEach(fn => fn()); host.remove(); context.signal?.removeEventListener('abort', dispose); }
  context.signal?.addEventListener('abort', dispose, { once: true });
  return dispose;
}
