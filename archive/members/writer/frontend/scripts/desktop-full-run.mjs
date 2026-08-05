import { _electron as electron } from 'playwright'
import { spawn, execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'

const frontendRoot = process.cwd()
const baseRunRoot = process.env.LAMWRITER_FULL_RUN_ROOT || 'E:\\WriterDesktopFullRun'
const runRoot = path.join(baseRunRoot, `run-${Date.now()}`)
const mode = process.env.LAMWRITER_FULL_RUN_MODE || 'low'
const taskText = process.env.LAMWRITER_FULL_RUN_TASK || '开发一个视频剪辑软件'
const intervalMs = Number(process.env.LAMWRITER_FULL_RUN_INTERVAL_MS || 60000)
const maxMs = Number(process.env.LAMWRITER_FULL_RUN_MAX_MS || 2700000)

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

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

async function prepare() {
  const workRoot = path.join(runRoot, `video-${mode}`)
  const dataDir = path.join(runRoot, `data-${mode}`)
  await fs.rm(runRoot, { recursive: true, force: true })
  await fs.mkdir(workRoot, { recursive: true })
  await fs.mkdir(dataDir, { recursive: true })
  execFileSync('git', ['init'], { cwd: workRoot, stdio: 'ignore' })
  execFileSync('git', ['config', 'user.name', 'Writer Full Run'], { cwd: workRoot, stdio: 'ignore' })
  execFileSync('git', ['config', 'user.email', 'writer-full-run@example.local'], { cwd: workRoot, stdio: 'ignore' })
  return { workRoot, dataDir }
}

async function collect(page, workRoot, startedAt, iteration) {
  const ui = await page.evaluate(async () => {
    const apiBase = window.lamwriterDesktop?.apiBase || ''
    const getJson = async (url) => {
      try {
        const res = await fetch(`${apiBase}${url}`)
        return res.ok ? res.json() : { status: res.status, error: await res.text() }
      } catch (error) {
        return { error: String(error) }
      }
    }
    const sessions = await getJson('/api/sessions?limit=20')
    const active = Array.isArray(sessions) ? sessions[0] : null
    const sessionId = active?.id || ''
    return {
      apiBase,
      title: document.title,
      text: document.body.innerText.slice(0, 9000),
      runStatus: document.querySelector('.run-status')?.textContent || '',
      hasDecisionCard: Boolean(document.querySelector('.decision-card')),
      decisionButtons: Array.from(document.querySelectorAll('.decision-option')).map((el) => el.textContent?.trim() || ''),
      hasChangeReview: Boolean(document.querySelector('.change-review-card')),
      session: active,
      steps: sessionId ? await getJson(`/api/sessions/${sessionId}/steps`) : [],
      messages: sessionId ? await getJson(`/api/sessions/${sessionId}/messages`) : [],
      graph: sessionId ? await getJson(`/api/sessions/${sessionId}/git-graph`) : null,
      changes: sessionId ? await getJson(`/api/sessions/${sessionId}/changes`) : null,
    }
  })

  let files = []
  try {
    const out = execFileSync(
      'powershell',
      ['-NoProfile', '-Command', `Get-ChildItem -LiteralPath '${workRoot}' -Recurse -File | Where-Object { $_.FullName -notmatch '\\\\.git\\\\' } | Select-Object -ExpandProperty FullName`],
      { encoding: 'utf8' },
    )
    files = out.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
  } catch {}

  let gitStatus = ''
  let gitBranch = ''
  let gitLog = ''
  try {
    gitStatus = execFileSync('git', ['status', '--short'], { cwd: workRoot, encoding: 'utf8' })
    gitBranch = execFileSync('git', ['branch', '--show-current'], { cwd: workRoot, encoding: 'utf8' }).trim()
    gitLog = execFileSync('git', ['log', '--oneline', '--decorate', '--all', '-8'], { cwd: workRoot, encoding: 'utf8' })
  } catch {}

  return {
    iteration,
    elapsed_ms: Date.now() - startedAt,
    sampled_at: new Date().toISOString(),
    ui,
    files,
    git: { branch: gitBranch, status: gitStatus, log: gitLog },
  }
}

function isTerminal(sample) {
  const status = sample.ui.runStatus || ''
  const text = sample.ui.text || ''
  if (/完成|已完成|Complete|Done/.test(status)) return true
  if (/writer_lifecycle.*done|任务完成/.test(text)) return true
  return false
}

async function maybeClickDecision(page, samples) {
  const buttons = page.locator('.decision-option')
  const count = await buttons.count()
  if (count === 0) {
    const hasDecision = await page.locator('.decision-card').count()
    const status = await page.locator('.run-status').textContent().catch(() => '')
    if (hasDecision > 0 || /等待用户|Waiting/i.test(status || '')) {
      samples.push({
        iteration: 'decision-text-confirm',
        elapsed_ms: null,
        sampled_at: new Date().toISOString(),
        status,
      })
      await page.locator('.floating-composer textarea').fill('确认，继续执行')
      await page.locator('.floating-composer button.send').click()
      return true
    }
    return false
  }
  const labels = []
  for (let i = 0; i < count; i += 1) labels.push((await buttons.nth(i).textContent())?.trim() || '')
  samples.push({
    iteration: 'decision-click',
    elapsed_ms: null,
    sampled_at: new Date().toISOString(),
    decision_buttons: labels,
  })
  const preferred = labels.findIndex((x) => /继续完整|继续|continue|accept|确认|执行/.test(x))
  await buttons.nth(preferred >= 0 ? preferred : 0).click()
  return true
}

async function openLeftDrawer(page) {
  await page.locator('.edge-left').dispatchEvent('mouseenter')
  await page.waitForSelector('.writer-shell.left-open')
}

async function main() {
  const { workRoot, dataDir } = await prepare()
  const reportPath = path.join(runRoot, `full-run-${Date.now()}.json`)
  await fs.mkdir(baseRunRoot, { recursive: true })
  const livePath = path.join(baseRunRoot, 'live.json')
  const logPath = path.join(runRoot, 'full-run.log')
  const samples = []
  const screenshots = []

  let vite = null
  if (!(await canReach('http://127.0.0.1:6174'))) {
    vite = spawn('npm.cmd', ['run', 'dev', '--', '--host', '127.0.0.1', '--strictPort'], {
      cwd: frontendRoot,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: true,
    })
  }
  await waitForUrl('http://127.0.0.1:6174')

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
  page.setDefaultTimeout(45000)
  const consoleMessages = []
  const pageErrors = []
  page.on('console', (msg) => consoleMessages.push(`${msg.type()}: ${msg.text()}`))
  page.on('pageerror', (err) => pageErrors.push(String(err)))

  try {
    await page.waitForSelector('.writer-shell')
    await openLeftDrawer(page)
    await page.locator('.drawer-left .icon-btn').click()
    await page.locator('.modal-card input').nth(0).fill(`视频剪辑完整验证-${mode}`)
    await page.locator('.modal-card input').nth(1).fill(workRoot)
    await page.locator('.modal-actions .btn-primary').click()
    await sleep(800)
    await openLeftDrawer(page)
    await page.locator('.project-action.add').first().click()
    await page.locator('.modal-card input').first().fill(`完整任务-${mode}`)
    await page.locator('.modal-actions .btn-primary').click()
    await page.waitForSelector('.thread-header h1')
    await page.locator('button[aria-label="质量档位"]').click()
    await page.locator('.quality-menu .composer-menu-item').filter({ hasText: mode }).first().click()
    await page.locator('.floating-composer textarea').fill(taskText)
    await page.locator('.floating-composer button.send').click()

    const startedAt = Date.now()
    let iteration = 0
    while (Date.now() - startedAt < maxMs) {
      await sleep(iteration === 0 ? 5000 : intervalMs)
      await maybeClickDecision(page, samples)
      const sample = await collect(page, workRoot, startedAt, iteration)
      samples.push(sample)
      const screenshotPath = path.join(runRoot, `shot-${String(iteration).padStart(3, '0')}.png`)
      try {
        await page.screenshot({ path: screenshotPath, fullPage: true, timeout: 15000 })
        screenshots.push(screenshotPath)
      } catch (error) {
        samples.push({
          iteration: `screenshot-failed-${iteration}`,
          elapsed_ms: Date.now() - startedAt,
          sampled_at: new Date().toISOString(),
          error: String(error),
        })
      }
      const line = `[${new Date().toISOString()}] #${iteration} ${Math.round(sample.elapsed_ms / 1000)}s status=${sample.ui.runStatus} files=${sample.files.length} steps=${Array.isArray(sample.ui.steps) ? sample.ui.steps.length : 'n/a'} decision=${sample.ui.hasDecisionCard}\n`
      await fs.appendFile(logPath, line, 'utf8')
      await fs.writeFile(livePath, JSON.stringify({ reportPath, workRoot, dataDir, mode, taskText, latest: sample, consoleMessages, pageErrors }, null, 2), 'utf8')
      if (isTerminal(sample)) break
      iteration += 1
    }
  } finally {
    const finalReport = { taskText, mode, workRoot, dataDir, maxMs, intervalMs, samples, screenshots, consoleMessages, pageErrors }
    await fs.writeFile(reportPath, JSON.stringify(finalReport, null, 2), 'utf8')
    await fs.writeFile(livePath, JSON.stringify({ reportPath, workRoot, dataDir, mode, taskText, latest: samples.at(-1), consoleMessages, pageErrors }, null, 2), 'utf8')
    await app.close().catch(() => {})
    if (vite?.pid) {
      try {
        execFileSync('taskkill', ['/PID', String(vite.pid), '/T', '/F'], { stdio: 'ignore' })
      } catch {
        vite.kill()
      }
    }
    console.log(reportPath)
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
