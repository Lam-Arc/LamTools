/** user:“该修修”+(发布纯 JavaScript，挂点重建时重新绑定，移除后停止轮询)。 */
(() => {
  const selector = '[data-plugin-entry="bili-scroll"]';
  let timer = null;
  function esc(value) {
    const node = document.createElement('span');
    node.textContent = String(value || '');
    return node.innerHTML;
  }
  async function render() {
    const bridge = window.LamToolsPluginRPC;
    if (!bridge) return;
    const [reports, brief] = await Promise.all([
      bridge('bili-scroll.reports.list').catch(() => ({})),
      bridge('bili-scroll.duty.brief').catch(() => ({})),
    ]);
    const seen = Array.isArray(brief.seen_recent) ? brief.seen_recent : [];
    for (const container of document.querySelectorAll(selector)) {
      const status = container.querySelector('[data-wall-status]');
      const list = container.querySelector('[data-wall-list]');
      if (status) status.textContent = `日报 ${(reports.reports || []).length} 份 · 已看 ${seen.length} 条`;
      if (list) list.innerHTML = seen.filter(row => /^BV[0-9A-Za-z]{8,}$/.test(row.bvid)).map(row => {
        const badge = row.status === 'picked' ? '挑了' : row.status === 'commented' ? '评论' : '跳过';
        const link = `https://www.bilibili.com/video/${encodeURIComponent(row.bvid)}`;
        return `<div class="bili-card"><strong>${esc(row.title || row.bvid)}</strong>` +
          `<span>${esc(row.up)} · ${badge}</span>` +
          `<a href="${link}" target="_blank" rel="noreferrer">${link}</a></div>`;
      }).join('') || '<div class="bili-card">还没有记录——先跑一轮值班。</div>';
    }
  }
  function mount() {
    const containers = document.querySelectorAll(selector);
    let added = false;
    for (const container of containers) {
      if (container.dataset.biliMounted) continue;
      container.dataset.biliMounted = 'true';
      container.innerHTML = '<div data-wall-status class="bili-wall-status">加载中…</div><div data-wall-list class="bili-wall-list"></div>';
      added = true;
    }
    if (containers.length && timer === null) timer = window.setInterval(() => void render(), 30000);
    if (!containers.length && timer !== null) { window.clearInterval(timer); timer = null; }
    if (added) void render();
  }
  new MutationObserver(mount).observe(document.body, { childList: true, subtree: true });
  mount();
})();
