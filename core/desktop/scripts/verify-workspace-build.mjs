import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { preview } from 'vite'

// user:“中间消失了”+(使用真实生产产物检查恢复已有标签和切换 Browser，覆盖只在打包后发生的空白)。
const server = await preview({
  configFile: false,
  root: fileURLToPath(new URL('../', import.meta.url)),
  preview: { host: '127.0.0.1', port: 0 },
})
let browser
try {
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.route(`${origin}/api/**`, route => {
    const path = new URL(route.request().url()).pathname
    const json = path.endsWith('/projects') ? { projects: [] }
      : path.endsWith('/sessions') ? [{ id: 'test-chat', title: 'Test chat' }]
        : {}
    return route.fulfill({ json })
  })
  await page.routeWebSocket('**/*', socket => socket.onMessage(raw => {
    const request = JSON.parse(raw)
    if (request.id === undefined) return
    socket.send(JSON.stringify({ jsonrpc: '2.0', id: request.id, result: { value: { completed: true } } }))
  }))
  await page.addInitScript(origin => {
    window.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: 'main' }, currentWebview: { label: 'main', windowLabel: 'main' } },
      transformCallback: () => 1,
      invoke: async command => {
        if (command === 'get_api_base') return origin
        if (command === 'get_app_info') return { name: 'Sunday', version: '0.0.0' }
        return null
      },
    }
    const surfaces = {
      'agent-main': { id: 'agent-main', kind: 'agent', title: 'Agent' },
      'files-7': { id: 'files-7', kind: 'file', fileView: 'files', title: 'Files' },
      'browser-10': { id: 'browser-10', kind: 'browser', title: 'New tab', resource: '' },
    }
    localStorage.setItem('lamtools.core.ui:split-workspace', JSON.stringify({
      version: 4,
      surfaces,
      tree: { kind: 'leaf', area: { id: 'main', role: 'main', tabs: Object.keys(surfaces), active: 'agent-main' } },
      prefs: { layout: 'agent', compact: true },
    }))
  }, origin)
  await page.goto(origin)
  await page.locator('[data-content-root]').click({ timeout: 10000 })
  await page.getByText('Browser', { exact: true }).click({ timeout: 5000 })
  const tab = page.locator('[data-ws2-tab="browser-10"]')
  const address = page.locator('[data-browser-slot="address"]')
  await tab.waitFor({ state: 'visible', timeout: 5000 })
  await address.waitFor({ state: 'visible', timeout: 5000 })
  assert.ok((await address.boundingBox()).width > 0, 'Browser address bar has usable width')
  await address.fill('example.test')
  assert.equal(await address.inputValue(), 'example.test')
  console.log('Packaged Browser shows its restored tab strip and an editable address bar.')
} finally {
  await browser?.close()
  await new Promise(resolve => server.httpServer.close(resolve))
}
