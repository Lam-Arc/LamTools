import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'

const requireFromFrontend = createRequire('E:/LamTools/members/writer/frontend/package.json')
const { _electron: electron } = requireFromFrontend('playwright')

const task = '开发一个本地视频剪辑软件'
const exePath = 'E:/LamTools/members/writer/frontend/release/win-unpacked/LamWriter.exe'
const stamp = Date.now()
const workRoot = `E:/writertest/long-task-work-${stamp}`
const observerRoot = `E:/writertest/long-task-observer-${stamp}`
const logPath = `${observerRoot}/observer.log`
const summaryPath = `${observerRoot}/summary.json`
const screenshotDir = `${observerRoot}/screens`
const maxMinutes = Number(process.env.LAMWRITER_LONG_TASK_MINUTES || '90')
const intervalMs = Number(process.env.LAMWRITER_LONG_TASK_INTERVAL_MS || '60000')
const autoConfirm = process.env.LAMWRITER_LONG_TASK_AUTO_CONFIRM === '1'

async function appendLog(line) {
  const text = `[${new Date().toISOString()}] ${line}\n`
  process.stdout.write(text)
  await fs.appendFile(logPath, text, 'utf8')
}

async function request(apiBase, method, url, body) {
  const response = await fetch(`${apiBase}${url}`, {
    method,
    headers: { 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  const text = await response.text()
  if (!response.ok) {
    throw new Error(`${method} ${url} ${response.status}: ${text.slice(0, 800)}`)
  }
  return text ? JSON.parse(text) : null
}

async function readBody(page) {
  try {
    return (await page.locator('body').innerText()).replace(/\s+/g, ' ')
  } catch {
    return ''
  }
}

function compact(text, size = 520) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  if (clean.length <= size) return clean
  return `${clean.slice(0, size)}...`
}

async function countFiles(root) {
  let count = 0
  const samples = []
  async function walk(dir) {
    let entries = []
    try {
      entries = await fs.readdir(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      if (entry.name === '.git' || entry.name === 'node_modules') continue
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        await walk(full)
      } else {
        count += 1
        if (samples.length < 12) samples.push(path.relative(root, full))
      }
    }
  }
  await walk(root)
  return { count, samples }
}

function latest(items, count = 5) {
  return Array.isArray(items) ? items.slice(-count) : []
}

async function main() {
  await fs.mkdir(screenshotDir, { recursive: true })
  await fs.mkdir(workRoot, { recursive: true })
  await appendLog(`start exe=${exePath}`)

  const app = await electron.launch({ executablePath: exePath })
  const page = await app.firstWindow({ timeout: 45000 })
  page.on('console', async (msg) => {
    if (msg.type() === 'error') await appendLog(`console-error ${msg.text()}`)
  })
  page.on('pageerror', async (error) => {
    await appendLog(`page-error ${error.message}`)
  })
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(3500)

  const apiBase = await page.evaluate(() => window.lamwriterDesktop?.apiBase || '')
  await appendLog(`api=${apiBase}`)
  const health = await request(apiBase, 'GET', '/api/health')
  await appendLog(`health=${JSON.stringify(health)}`)

  const project = await request(apiBase, 'POST', '/api/projects', {
    name: `长任务测试 ${stamp}`,
    work_root: workRoot.replaceAll('/', '\\'),
  })
  const session = await request(apiBase, 'POST', '/api/sessions', {
    title: `视频剪辑软件 ${stamp}`,
    work_root: workRoot.replaceAll('/', '\\'),
    mode: 'EXECUTE',
    project_id: project.id,
  })
  await appendLog(`project=${project.id} session=${session.id} workRoot=${workRoot}`)

  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  const bodyBefore = await readBody(page)
  if (!bodyBefore.includes(session.id.slice(0, 8))) {
    await appendLog(`warning active session not obvious body=${compact(bodyBefore)}`)
  }

  await page.locator('textarea').fill(task)
  await page.locator('button.send').click()
  await appendLog(`submitted task=${task}`)
  await page.screenshot({ path: `${screenshotDir}/submitted.png`, fullPage: true })

  const started = Date.now()
  let finalReason = 'max_minutes'
  let lastStepCount = 0
  let lastFileCount = 0
  let lastBody = ''
  let autoConfirmCount = 0

  for (let minute = 0; minute <= maxMinutes; minute += 1) {
    if (minute > 0) await new Promise((resolve) => setTimeout(resolve, intervalMs))

    const [sessionState, messages, steps, changes] = await Promise.all([
      request(apiBase, 'GET', `/api/sessions/${session.id}`),
      request(apiBase, 'GET', `/api/sessions/${session.id}/messages`),
      request(apiBase, 'GET', `/api/sessions/${session.id}/steps`),
      request(apiBase, 'GET', `/api/sessions/${session.id}/changes`).catch((error) => ({ error: error.message })),
    ])
    const fileState = await countFiles(workRoot)
    const body = await readBody(page)
    lastBody = body
    lastStepCount = steps.length
    lastFileCount = fileState.count

    const running = body.includes('运行中') || body.includes('Writer 正在处理') || body.includes('正在执行') || body.includes('模型等待')
    const uiWaiting = body.includes('等待用户决策') || body.includes('暂停中')
    const waiting = uiWaiting && sessionState.phase !== 'executing'
    const done = body.includes('已完成') && !running
    const failed = body.includes('失败') || body.includes('错误')
    const latestSteps = latest(steps, 5).map((step) => ({
      n: step.step_number,
      type: step.step_type,
      status: step.status,
      tool: step.tool_name,
      content: compact(step.content, 80),
      error: compact(step.error, 80),
    }))
    const latestMessages = latest(messages, 3).map((message) => ({
      role: message.role,
      content: compact(message.content, 120),
    }))
    const changeFiles = Array.isArray(changes.files) ? changes.files.length : 0
    const line = {
      minute,
      phase: sessionState.phase,
      status: sessionState.status,
      running,
      uiWaiting,
      waiting,
      done,
      failed,
      steps: steps.length,
      files: fileState.count,
      changedFiles: changeFiles,
      samples: fileState.samples,
      latestSteps,
      latestMessages,
      uiTail: compact(body.slice(-900), 360),
    }
    await appendLog(JSON.stringify(line, null, 0))
    await page.screenshot({ path: `${screenshotDir}/minute-${String(minute).padStart(3, '0')}.png`, fullPage: true })

    if (waiting && autoConfirm && autoConfirmCount < 3) {
      autoConfirmCount += 1
      await appendLog(`auto_confirm attempt=${autoConfirmCount}`)
      try {
        const confirm = page.getByText('确认并继续执行').first()
        await confirm.click({ timeout: 10000 })
        await page.screenshot({ path: `${screenshotDir}/auto-confirm-${autoConfirmCount}.png`, fullPage: true })
        await new Promise((resolve) => setTimeout(resolve, 5000))
        continue
      } catch (error) {
        await appendLog(`auto_confirm_failed=${error.message}`)
      }
    }

    if (waiting) {
      finalReason = 'waiting_for_user'
      break
    }
    if (failed && !running) {
      finalReason = 'failed_or_error'
      break
    }
    if (done && steps.length > 0 && fileState.count > 0) {
      finalReason = 'done_with_files'
      break
    }
  }

  const summary = {
    finalReason,
    elapsedMinutes: Math.round((Date.now() - started) / 60000),
    apiBase,
    projectId: project.id,
    sessionId: session.id,
    workRoot,
    observerRoot,
    autoConfirm,
    autoConfirmCount,
    steps: lastStepCount,
    files: lastFileCount,
    uiTail: compact(lastBody.slice(-1400), 900),
    logPath,
    screenshotDir,
  }
  await fs.writeFile(summaryPath, JSON.stringify(summary, null, 2), 'utf8')
  await appendLog(`summary=${JSON.stringify(summary)}`)
  await app.close()
}

main().catch(async (error) => {
  await appendLog(`fatal=${error.stack || error.message || String(error)}`).catch(() => {})
  process.exit(1)
})
