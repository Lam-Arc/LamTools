/** user:“支持一下”+(卡片墙作为独立分屏页面；计时器、请求与 DOM 都归当前实例)。 */
export function mount(root, context) {
  let disposed = false, generation = 0, timer;
  const section = document.createElement('section');
  const heading = document.createElement('h3'); heading.textContent = '值班近况';
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  const refresh = document.createElement('button'); refresh.type = 'button'; refresh.className = 'split-text-button'; refresh.textContent = '刷新';
  const list = document.createElement('div');
  section.append(heading, refresh, status, list); root.append(section);

  async function render() {
    const current = ++generation;
    refresh.disabled = true;
    try {
      const [reports, brief] = await Promise.all([context.rpc('bili-scroll.reports.list', {}), context.rpc('bili-scroll.duty.brief', {})]);
      if (disposed || context.signal.aborted || current !== generation) return;
      const seen = Array.isArray(brief.seen_recent) ? brief.seen_recent : [];
      status.textContent = `日报 ${(reports.reports || []).length} 份 · 已看 ${seen.length} 条`;
      list.replaceChildren();
      for (const row of seen) {
        const card = document.createElement('article');
        const title = document.createElement('strong'); title.textContent = row.title || row.bvid || '';
        const detail = document.createElement('p'); detail.textContent = `${row.up || ''} · ${row.bvid || ''} · ${row.status || ''}`;
        card.append(title, detail); list.append(card);
      }
      if (!seen.length) list.textContent = '还没有记录，运行一轮值班后会显示在这里。';
    } catch (error) {
      if (!disposed && current === generation) status.textContent = `读取失败：${String(error)}`;
    } finally {
      if (!disposed && current === generation) refresh.disabled = false;
    }
  }
  function stopTimer() { if (timer !== undefined) { window.clearInterval(timer); timer = undefined; } }
  function visibility(visible) {
    stopTimer();
    if (visible && !disposed) { void render(); timer = window.setInterval(() => void render(), 30000); }
  }
  const unsubscribe = context.onVisibilityChange(visibility);
  function dispose() {
    if (disposed) return;
    disposed = true; generation++; stopTimer(); unsubscribe();
    refresh.removeEventListener('click', render); context.signal.removeEventListener('abort', dispose);
    section.remove();
  }
  refresh.addEventListener('click', render);
  context.signal.addEventListener('abort', dispose, { once: true });
  visibility(context.visible);
  return dispose;
}
