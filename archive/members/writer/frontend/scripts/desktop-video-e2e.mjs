import { _electron as electron } from 'playwright'
import { spawn, execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'

const repoRoot = path.resolve(process.cwd(), '..')
const frontendRoot = process.cwd()
const testRoot = 'E:\\WriterDesktopE2E'
const taskText = '开发一个视频剪辑软件'
const modes = (process.env.LAMWRITER_E2E_MODES || 'low,medium,high,crazy')
  .split(',')
  .map((x) => x.trim())
  .filter(Boolean)
const runMs = Number(process.env.LAMWRITER_E2E_RUN_MS || 720000)

function waitForUrl(url, timeoutMs = 60000) {
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

async function prepareWorkRoot(mode) {
  const workRoot = path.join(testRoot, `video-${mode}`)
  const dataDir = path.join(testRoot, `data-${mode}`)
  await fs.mkdir(workRoot, { recursive: true })
  await fs.mkdir(dataDir, { recursive: true })
  try {
    execFileSync('git', ['init'], { cwd: workRoot, stdio: 'ignore' })
    execFileSync('git', ['config', 'user.name', 'Writer E2E'], { cwd: workRoot, stdio: 'ignore' })
    execFileSync('git', ['config', 'user.email', 'writer-e2e@example.local'], { cwd: workRoot, stdio: 'ignore' })
  } catch {
    // Git is observed later. A missing git binary should not hide UI/runtime failures.
  }
  return { workRoot, dataDir }
}

async function collectState(page) {
  return page.evaluate(async () => {
    const apiBase = window.lamwriterDesktop?.apiBase || ''
    const getJson = async (url) => {
      const res = await fetch(`${apiBase}${url}`)
      return res.ok ? res.json() : { error: await res.text(), status: res.status }
    }
    const sessions = await getJson('/api/sessions?limit=20')
    const activeSessionText = document.querySelector('.thread-header span')?.textContent || ''
    const steps = []
    const messages = []
    const graphs = []
    for (const session of Array.isArray(sessions) ? sessions : []) {
      steps.push({ session_id: session.id, data: await getJson(`/api/sessions/${session.id}/steps`) })
      messages.push({ session_id: session.id, data: await getJson(`/api/sessions/${session.id}/messages`) })
      graphs.push({ session_id: session.id, data: await getJson(`/api/sessions/${session.id}/git-graph`) })
    }
    return {
      apiBase,
      hasDesktopBridge: Boolean(window.lamwriterDesktop),
      hasSelectDirectory: typeof window.lamwriterDesktop?.selectDirectory === 'function',
      title: document.title,
      activeSessionText,
      runStatus: document.querySelector('.run-status')?.textContent || '',
      runtimeText: document.body.innerText.slice(0, 5000),
      sessions,
      steps,
      messages,
      graphs,
    }
  })
}

async function launchCase(mode) {
  const { workRoot, dataDir } = await prepareWorkRoot(mode)
  const app = await electron.launch({
    args: ['electron/main.cjs'],
    cwd: frontendRoot,
    env: {
      ...process.env,
      LAMWRITER_DATA_DIR: dataDir,
      LAMWRITER_WRITER_WORK_ROOT: workRoot,
    },
  })
  const page = await app.firstWindow()
  page.setDefaultTimeout(30000)
  const consoleMessages = []
  const pageErrors = []
  page.on('console', (msg) => consoleMessages.push(`${msg.type()}: ${msg.text()}`))
  page.on('pageerror', (err) => pageErrors.push(String(err)))

  await page.waitForSelector('.writer-shell')
  await page.keyboard.press('Control+Tab')
  await page.waitForSelector('.writer-shell.left-open')
  await page.locator('.drawer-left .icon-btn[title="新建项目"]').click()
  await page.locator('.modal-card input').nth(0).fill(`视频剪辑-${mode}`)
  await page.locator('.modal-card input').nth(1).fill(workRoot)
  await page.locator('.modal-actions .btn-primary').click()
  await page.waitForTimeout(800)

  await page.keyboard.press('Control+Tab')
  await page.waitForSelector('.writer-shell.left-open')
  await page.locator('.project-action.add').first().click()
  await page.locator('.modal-card input').first().fill(`任务-${mode}`)
  await page.locator('.modal-actions .btn-primary').click()
  await page.waitForSelector('.thread-header h1')

  await page.locator('button[aria-label="质量档位"]').click()
  await page.locator('.quality-menu .composer-menu-item').filter({ hasText: mode }).first().click()
  await page.locator('.floating-composer textarea').fill(taskText)
  await page.locator('.floating-composer button.send').click()

  await page.waitForTimeout(runMs)
  const state = await collectState(page)
  await app.close()
  return {
    mode,
    workRoot,
    dataDir,
    consoleMessages,
    pageErrors,
    state,
  }
}

async function main() {
  await fs.rm(testRoot, { recursive: true, force: true })
  await fs.mkdir(testRoot, { recursive: true })

  let vite = null
  const viteLog = []
  if (!(await canReach('http://127.0.0.1:6174'))) {
    vite = spawn('npm.cmd', ['run', 'dev', '--', '--host', '127.0.0.1', '--strictPort'], {
      cwd: frontendRoot,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: true,
    })
    vite.stdout.on('data', (chunk) => viteLog.push(String(chunk)))
    vite.stderr.on('data', (chunk) => viteLog.push(String(chunk)))
  } else {
    viteLog.push('Reused existing Vite server on http://127.0.0.1:6174')
  }

  try {
    await waitForUrl('http://127.0.0.1:6174')
    const results = await Promise.all(modes.map((mode) => launchCase(mode)))
    const reportPath = path.join(testRoot, `desktop-video-e2e-${Date.now()}.json`)
    await fs.writeFile(reportPath, JSON.stringify({ taskText, modes, runMs, results, viteLog }, null, 2), 'utf8')
    console.log(reportPath)
  } finally {
    if (vite?.pid) {
      try {
        execFileSync('taskkill', ['/PID', String(vite.pid), '/T', '/F'], { stdio: 'ignore' })
      } catch {
        vite.kill()
      }
    }
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
