// user:“实现这个插件，也正好实验我们的新插件架构”+(代码验收八个页面、共享轮询、文本安全与关闭清理)。
import { afterEach, expect, it, vi } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { mount } from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/page.mjs';
import { createNetworkStore } from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/store.mjs';

afterEach(() => { vi.useRealTimers(); document.body.replaceChildren(); });
const snapshot = { controller_pid: 123, revision: 0, settings: { mode: 'local', sample_seconds: 5 }, proxy: { running: false }, history: [], events: [], rules: [], reports: [], downloads: [], automations: [] };
it('renders the four visible pages and disposes without leaving polling', async () => {
  vi.useFakeTimers();
  const root = document.createElement('div'); document.body.append(root);
  const controller = new AbortController();
  const rpc = vi.fn(async method => method.endsWith('.status') ? snapshot : { tasks: [] });
  const dispose = mount(root, { rpc, signal: controller.signal, visible: true, onVisibilityChange: () => () => {} });
  await flushPromises();
  // user:“概览、下载、互联、诊断四个视图，代理和高级设置收进设置页”+(构建产物同样要能逐页渲染)。
  for (const page of ['overview', 'transfer', 'devices', 'diagnose']) {
    root.querySelector(`[data-page="${page}"]`).click();
    await flushPromises();
    expect(root.querySelector('.ne-content').textContent.length).toBeGreaterThan(10);
  }
  controller.abort(); dispose();
  const calls = rpc.mock.calls.length;
  await vi.advanceTimersByTimeAsync(15000);
  expect(rpc.mock.calls.length).toBe(calls);
  expect(root.children).toHaveLength(0);
});

it('two subscribers share one request and closing both stops polling', async () => {
  vi.useFakeTimers(); const store = createNetworkStore();
  const rpc = vi.fn(async () => snapshot), update = vi.fn();
  const a = store.subscribe({ rpc, update, visible: () => true });
  const b = store.subscribe({ rpc, update, visible: () => true });
  await flushPromises(); expect(rpc).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(5000); expect(rpc).toHaveBeenCalledTimes(2);
  a(); b(); await vi.advanceTimersByTimeAsync(15000); expect(rpc).toHaveBeenCalledTimes(2);
});

it('does not interpret diagnostic text as HTML', async () => {
  const root = document.createElement('div'); document.body.append(root);
  const controller = new AbortController();
  const evil = '<img src=x onerror=alert(1)>';
  // 下载文件名与事件都来自后台，任何一段都不能被当成 HTML 解释。
  const rpc = vi.fn(async method => method.endsWith('.status')
    ? { ...snapshot, events: [{ message: evil, kind: 'test' }], downloads: [{ gid: 'x', filename: evil, status: 'active', totalLength: '1', completedLength: '0', downloadSpeed: '0' }] }
    : { tasks: [] });
  const dispose = mount(root, { rpc, signal: controller.signal, visible: true });
  await flushPromises();
  root.querySelector('[data-page="transfer"]').click();
  await flushPromises();
  await new Promise(resolve => setTimeout(resolve, 0));
  await flushPromises();
  expect(root.querySelector('img')).toBeNull();
  expect(root.textContent).toContain(evil);
  controller.abort(); dispose();
});
