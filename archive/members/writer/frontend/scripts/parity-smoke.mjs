import { _electron as electron, chromium } from 'playwright'
import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'

const frontendRoot = process.cwd()
const repoRoot = path.resolve(frontendRoot, '..', '..')
const artifactRoot = path.join(repoRoot, 'tmp', 'writer-parity-smoke')
const webUrl = process.env.LAMWRITER_PARITY_WEB_URL || 'http://127.0.0.1:6174/'
const packagedExe = process.env.LAMWRITER_PARITY_EXE
  || path.join(frontendRoot, 'release', 'win-unpacked', 'LamWriter.exe')

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function waitForUrl(url, timeoutMs = 45000) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume()
        if (res.statusCode && res.statusCode < 500) {
          resolve()
          return
        }
        retry()
      })
      req.on('error', retry)
      req.setTimeout(1200, () => {
        req.destroy()
        retry()
      })
    }
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timeout waiting for ${url}`))
        return
      }
      setTimeout(tick, 300)
    }
    tick()
  })
}

async function canReach(url) {
  try {
    await waitForUrl(url, 1500)
    return true
  } catch {
    return false
  }
}

async function startViteIfNeeded() {
  if (await canReach(webUrl)) return null
  const child = spawn('npm.cmd', ['run', 'dev', '--', '--host', '127.0.0.1', '--strictPort'], {
    cwd: frontendRoot,
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: true,
  })
  await waitForUrl(webUrl)
  return child
}

async function inspectPage(page, targetName) {
  await page.waitForSelector('.writer-shell', { timeout: 30000 })
  const before = await page.evaluate(() => {
    const textarea = document.querySelector('textarea[placeholder="输入任务描述..."]')
    const send = document.querySelector('button.send')
    const rect = textarea?.getBoundingClientRect()
    const hit = rect ? document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2) : null
    return {
      href: location.href,
      origin: location.origin,
      apiBase: window.lamwriterDesktop?.apiBase || '',
      hasDesktopBridge: Boolean(window.lamwriterDesktop),
      hasSelectDirectory: typeof window.lamwriterDesktop?.selectDirectory === 'function',
      textarea: textarea ? {
        disabled: textarea.disabled,
        readOnly: textarea.readOnly,
        value: textarea.value,
        hitTag: hit?.tagName || '',
        hitClass: String(hit?.className || ''),
        hitPlaceholder: hit?.getAttribute?.('placeholder') || '',
        hitSame: hit === textarea || textarea.contains(hit),
      } : null,
      send: send ? {
        disabled: send.disabled,
        text: send.textContent || '',
      } : null,
    }
  })

  const textarea = page.locator('textarea[placeholder="输入任务描述..."]')
  await textarea.fill('', { timeout: 5000 })
  await textarea.click({ timeout: 5000 })
  await textarea.type(`parity-${targetName}`, { timeout: 5000 })

  const after = await page.evaluate(() => {
    const textarea = document.querySelector('textarea[placeholder="输入任务描述..."]')
    const send = document.querySelector('button.send')
    return {
      activeTag: document.activeElement?.tagName || '',
      activePlaceholder: document.activeElement?.getAttribute?.('placeholder') || '',
      textareaValue: textarea?.value || '',
      sendDisabled: send?.disabled === true,
    }
  })
  await textarea.fill('', { timeout: 5000 })

  const errors = []
  if (!before.textarea) errors.push('composer textarea missing')
  if (before.textarea?.disabled) errors.push('composer textarea disabled')
  if (before.textarea?.readOnly) errors.push('composer textarea readonly')
  if (before.textarea && !before.textarea.hitSame) errors.push('composer textarea center is not clickable')
  if (after.textareaValue !== `parity-${targetName}`) errors.push('typed text did not reach textarea')
  if (after.sendDisabled) errors.push('send button stayed disabled after typing')

  return {
    target: targetName,
    ok: errors.length === 0,
    errors,
    before,
    after,
  }
}

async function runWeb() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage({ viewport: { width: 1320, height: 860 } })
  const consoleMessages = []
  const pageErrors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleMessages.push(msg.text())
  })
  page.on('pageerror', (err) => pageErrors.push(String(err)))
  try {
    await page.goto(webUrl, { waitUntil: 'domcontentloaded', timeout: 30000 })
    const result = await inspectPage(page, 'web')
    return { ...result, consoleMessages, pageErrors }
  } finally {
    await browser.close()
  }
}

async function runPackaged() {
  await fs.access(packagedExe)
  const userDataDir = path.join(artifactRoot, `electron-user-data-${Date.now()}`)
  const app = await electron.launch({
    executablePath: packagedExe,
    args: [`--user-data-dir=${userDataDir}`],
    env: process.env,
  })
  const page = await app.firstWindow()
  page.setDefaultTimeout(30000)
  const consoleMessages = []
  const pageErrors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleMessages.push(msg.text())
  })
  page.on('pageerror', (err) => pageErrors.push(String(err)))
  try {
    await sleep(500)
    const result = await inspectPage(page, 'app')
    return { ...result, consoleMessages, pageErrors }
  } finally {
    await app.close()
  }
}

async function main() {
  await fs.mkdir(artifactRoot, { recursive: true })
  const vite = await startViteIfNeeded()
  try {
    const results = []
    results.push(await runWeb())
    results.push(await runPackaged())
    const report = {
      generatedAt: new Date().toISOString(),
      webUrl,
      packagedExe,
      results,
    }
    const reportPath = path.join(artifactRoot, `parity-smoke-${Date.now()}.json`)
    await fs.writeFile(reportPath, JSON.stringify(report, null, 2), 'utf8')
    console.log(reportPath)
    const failed = results.filter((item) => !item.ok)
    if (failed.length > 0) {
      for (const item of failed) {
        console.error(`${item.target} failed: ${item.errors.join('; ')}`)
      }
      process.exitCode = 1
    }
  } finally {
    if (vite?.pid) {
      vite.kill()
    }
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
