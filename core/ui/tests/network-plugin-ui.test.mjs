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
  for (const page of ['home', 'overview', 'proxy', 'transfer']) {
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
  const rpc = vi.fn(async method => method.endsWith('.transfer.list')
    ? { tasks: [{ gid: 'x', filename: evil, status: 'active', totalLength: '1', completedLength: '0', downloadSpeed: '0' }] }
    : { ...snapshot, events: [{ message: evil, kind: 'test' }] });
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
