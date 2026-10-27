// user:“实现这个插件，也正好实验我们的新插件架构”+(插件设置中直接复用完整自绘界面，关闭后释放页面订阅)。
(function () {
  const source = document.currentScript.src;
  window.LamToolsPluginPanels = window.LamToolsPluginPanels || {};
  window.LamToolsPluginPanels['network-exploration'] = {
    async mount(root, api) {
      const pageUrl = new URL('../ui/page.mjs', source);
      pageUrl.searchParams.set('plugin-version', api.plugin.version);
      const page = await import(pageUrl.href);
      if (api.signal.aborted) return;
      return page.mount(root, { rpc: api.rpc, signal: api.signal, visible: true, onVisibilityChange: () => () => {} });
    }
  };
})();
