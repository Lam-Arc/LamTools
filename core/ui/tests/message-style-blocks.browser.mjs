// user:“不要出错”+(真实浏览器代码验收，不使用 Computer Use 或人工界面操作)。
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('..', import.meta.url))
const require = createRequire(resolve(root, 'package.json'))
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href)
const py = `import socket,uvicorn
from lamtools_core.app.factory import create_app
s=socket.socket();s.bind(('127.0.0.1',0));s.listen(128)
print(s.getsockname()[1],flush=True)
uvicorn.Server(uvicorn.Config(create_app(),log_level='error',lifespan='off')).run(sockets=[s])`
const backend = spawn('python', ['-u', '-c', py], { cwd: resolve(root, '..'), env: { ...process.env, PYTHONPATH: resolve(root, '../src') }, windowsHide: true })
let server, browser
try {
  const port = await new Promise((resolvePort, reject) => {
    let output = ''
    backend.stdout.on('data', chunk => { output += chunk; const match = /^(\d+)\r?\n/.exec(output); if (match) resolvePort(Number(match[1])) })
    backend.once('error', reject)
    backend.once('exit', code => reject(Error(`Backend exited: ${code}`)))
    backend.stderr.on('data', chunk => process.stderr.write(chunk))
  })
  server = await createServer({ root, configFile: resolve(root, 'vite.config.ts'), plugins: [{ name: 'acceptance-csp', configureServer(vite) {
    vite.middlewares.use((req, res, next) => {
      if (req.url?.endsWith('/message-style-blocks.html')) res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:*; frame-src http://127.0.0.1:*; img-src 'self' data:; font-src 'self' data:")
      next()
    })
  } }], server: { host: '127.0.0.1', port: 0, proxy: { '/api': { target: `http://127.0.0.1:${port}`, changeOrigin: true } } } })
  await server.listen()
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/tests/fixtures/message-style-blocks.html`)
  const frame = page.frameLocator('iframe')
  await expect(frame.locator('#counter')).toHaveText('0')
  await frame.locator('#counter').click()
  await expect(frame.locator('#counter')).toHaveText('1')
  await frame.locator('#amount').fill('75')
  await expect(frame.locator('#value')).toHaveText('75')
  await expect(frame.locator('body')).toHaveAttribute('data-isolated', 'yes')
  await expect(frame.locator('body')).toHaveAttribute('data-storage-blocked', 'yes')
  await expect(frame.locator('body')).toHaveAttribute('data-network-blocked', 'yes')
  await expect(page.locator('body')).not.toHaveAttribute('data-escaped', 'yes')
  await expect(frame.locator('body')).toHaveCSS('color', 'rgb(240, 240, 240)')
  await page.locator('main').evaluate(node => node.style.setProperty('--theme-main-text', 'rgb(10, 20, 30)'))
  await expect(frame.locator('body')).toHaveCSS('color', 'rgb(10, 20, 30)')
  await page.locator('details[data-style-block] summary').click()
  await expect(page.locator('details[data-style-block]')).toHaveAttribute('open', '')
  await page.locator('[data-writing-edit]').click()
  await page.locator('.writing-block textarea').fill('修改后的正文')
  await page.locator('[data-writing-edit]').click()
  await expect(page.locator('.writing-block')).toContainText('修改后的正文')
  await page.evaluate(() => { window.blockAcceptance.state.streaming = true })
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.evaluate(() => { window.blockAcceptance.state.streaming = false })
  await expect(frame.locator('#counter')).toHaveText('0')
  await page.evaluate(() => { window.blockAcceptance.state.content = window.blockAcceptance.fence('<script>throw new Error("fixture failure")</script>') })
  await expect(page.locator('.inline-visualization-error')).toBeVisible()
  await page.evaluate(() => { window.blockAcceptance.state.content = '普通回复' })
  await expect(page.locator('iframe')).toHaveCount(0)
  // Security violations are expected in the fixture. App errors are not.
  if (errors.some(message => !message.includes('fixture failure'))) throw Error(errors.join('\n'))
  console.log('PASS: live controls, isolation, network policy, inherited themes, writing edits, details, streaming, error fallback and disposal')
} finally {
  await browser?.close()
  await server?.close()
  backend.kill()
}
