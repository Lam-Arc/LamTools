// user:“插件窗口的所有东西都被渲染成了文本，它自己的样式好像全部都丢了”+(动态样式借用当前文档的 CSP nonce)。
export function attachPluginStyle(root: HTMLElement, css: string, owner: string): () => void {
  const document = root.ownerDocument
  const style = document.createElement('style')
  const nonce = document.querySelector<HTMLStyleElement>('style[nonce]')?.nonce
    || document.querySelector<HTMLLinkElement>('link[nonce]')?.nonce
  if (nonce) style.nonce = nonce
  style.dataset.pluginStyle = owner
  style.textContent = css
  document.head.append(style)
  // user:“如图，我不清楚这是不是你写出来的界面的设计的样子”+(没有可借用 nonce 或动态样式被策略拦截时，改用同页创建的本地样式资源)。
  if (!style.sheet) {
    style.remove()
    const view = document.defaultView
    if (!view?.URL?.createObjectURL) throw new Error('插件样式被桌面安全策略拦截')
    const url = view.URL.createObjectURL(new Blob([css], { type: 'text/css' }))
    const link = document.createElement('link')
    link.rel = 'stylesheet'; link.href = url; link.dataset.pluginStyle = owner
    let warning: HTMLElement | undefined
    let disposed = false
    link.addEventListener('error', () => {
      if (disposed) return
      warning = document.createElement('p')
      warning.setAttribute('role', 'alert')
      warning.textContent = '插件样式无法加载，请刷新页面或检查桌面版本'
      root.before(warning)
    }, { once: true })
    document.head.append(link)
    return () => { disposed = true; link.remove(); warning?.remove(); view.URL.revokeObjectURL(url) }
  }
  return () => style.remove()
}
