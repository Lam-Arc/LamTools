// user:“实现这个插件，也正好实验我们的新插件架构”+(所有面板共享轮询和后台快照，最后一个面板关闭后停止 UI 轮询)。
export function createNetworkStore() {
  const listeners = new Set();
  let state = null, error = '', timer, inflight = false, generation = 0;
  const active = () => [...listeners].find(listener => !listener.signal?.aborted && listener.visible());
  const publish = () => { for (const listener of listeners) if (!listener.signal?.aborted) listener.update(state, error); };
  function schedule() {
    clearTimeout(timer);
    if (active()) timer = setTimeout(() => void refresh(), 5000);
  }
  async function refresh() {
    const source = active();
    if (!source || inflight) return;
    inflight = true;
    const current = generation;
    try {
      const result = await source.rpc('network-exploration.status', {});
      if (current === generation) { state = result; error = ''; publish(); }
    } catch (cause) {
      if (current === generation) { error = cause instanceof Error ? cause.message : String(cause); publish(); }
    } finally { inflight = false; schedule(); }
  }
  function subscribe(listener) {
    listeners.add(listener); listener.update(state, error);
    void refresh();
    let disposed = false;
    const dispose = () => {
      if (disposed) return;
      disposed = true; listeners.delete(listener); listener.signal?.removeEventListener('abort', dispose);
      if (!listeners.size) { generation++; clearTimeout(timer); }
    };
    listener.signal?.addEventListener('abort', dispose, { once: true });
    return dispose;
  }
  return { subscribe, refresh, visibilityChanged() { if (active()) void refresh(); else clearTimeout(timer); }, get state() { return state; } };
}
export const networkStore = createNetworkStore();
export const bytes = value => {
  const number = Number(value || 0);
  if (number < 1024) return `${number.toFixed(0)} B`;
  if (number < 1048576) return `${(number / 1024).toFixed(1)} KB`;
  if (number < 1073741824) return `${(number / 1048576).toFixed(1)} MB`;
  return `${(number / 1073741824).toFixed(2)} GB`;
};
export function element(tag, text = '', className = '') {
  const node = document.createElement(tag); node.textContent = text;
  if (className) node.className = className;
  return node;
}
