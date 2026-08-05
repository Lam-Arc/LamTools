import { spawnSync } from 'node:child_process'
import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'

const frontendUrl = process.env.WRITER_FRONTEND_URL || 'http://127.0.0.1:6174'
const backendUrl = process.env.WRITER_BACKEND_URL || 'http://127.0.0.1:6173'
const headless = process.env.HEADLESS !== '0'
const runId = new Date().toISOString().replace(/[:.]/g, '-')
const artifactDir = new URL('../../../../tmp/writer-app-server-e2e/', import.meta.url)
const workRoot = new URL(`../../../../tmp/writer-app-server-e2e/workspaces/approval-${runId}/`, import.meta.url)
const workRootPath = fileURLToPath(workRoot)

const forbiddenRequestPatterns = [
  /\/api\/sessions\/[^/]+\/chat\b/,
  /\/api\/sessions\/events\b/,
  /\/api\/sessions\/[^/]+\/queued-inputs\b/,
  /\/api\/sessions\/[^/]+\/waiting-requests\b/,
  /\/api\/sessions\/[^/]+\/transcript\b/,
  /\/api\/sessions\/[^/]+\/cancel\b/,
  /\/api\/sessions\/[^/]+\/resume\b/,
  /\/api\/sessions\/[^/]+\/debug\/sse\b/,
]

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const text = await response.text()
  if (!response.ok) {
    throw new Error(`${options.method || 'GET'} ${url} failed ${response.status}: ${text.slice(0, 500)}`)
  }
  return text ? JSON.parse(text) : null
}

async function createSession() {
  await import('node:fs/promises').then((fs) => fs.mkdir(workRoot, { recursive: true }))
  return requestJson(`${backendUrl}/api/core/sessions`, {
    method: 'POST',
    body: JSON.stringify({
      title: `App Server Approval E2E ${runId}`,
      work_root: workRootPath,
    }),
  })
}

function isNavigationAbortPath(pathname) {
  return pathname === '/api/core/sessions'
    || /^\/api\/sessions\/[^/]+\/changes$/.test(pathname)
    || /^\/api\/sessions\/[^/]+\/agent-branches$/.test(pathname)
}

function seedApproval(sessionId, requestId) {
  const result = spawnSync(
    'py',
    ['-3.14', 'scripts/seed_app_server_approval.py', '--thread-id', sessionId, '--request-id', requestId],
    {
      cwd: new URL('../../backend/', import.meta.url),
      encoding: 'utf8',
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    },
  )
  if (result.status !== 0) {
    throw new Error(`Failed to seed approval:\n${result.stdout}\n${result.stderr}`)
  }
  return JSON.parse(result.stdout)
}

function elapsed(startedAt) {
  return Math.round(performance.now() - startedAt)
}

async function main() {
  const session = await createSession()
  const requestId = `approval-e2e-${runId}`
  seedApproval(session.id, requestId)

  const browser = await chromium.launch({ headless })
  const page = await browser.newPage()
  const consoleErrors = []
  const failedRequests = []
  const badResponses = []
  const forbiddenRequests = []
  const appServerSockets = []

  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => consoleErrors.push(error.message))
  page.on('request', (request) => {
    const url = request.url()
    if (forbiddenRequestPatterns.some((pattern) => pattern.test(url))) forbiddenRequests.push(url)
  })
  page.on('requestfailed', (request) => {
    const failureText = request.failure()?.errorText || ''
    const url = request.url()
    if (request.method() === 'GET' && failureText === 'net::ERR_ABORTED' && isNavigationAbortPath(new URL(url).pathname)) {
      return
    }
    failedRequests.push(`${request.method()} ${url} ${failureText}`)
  })
  page.on('response', (response) => {
    if (response.status() >= 400) {
      badResponses.push(`${response.status()} ${response.request().method()} ${response.url()}`)
    }
  })
  page.on('websocket', (socket) => {
    if (socket.url().includes('/api/app-server')) appServerSockets.push(socket.url())
  })

  try {
    await import('node:fs/promises').then((fs) => fs.mkdir(artifactDir, { recursive: true }))
    await page.goto(`${frontendUrl}/?session=${encodeURIComponent(session.id)}`, { waitUntil: 'networkidle' })
    await page.locator('textarea[placeholder="输入任务描述..."]').first().waitFor({ state: 'visible', timeout: 15_000 })
    await expandProcess(page)
    await page.locator('.decision-card').first().waitFor({ state: 'visible', timeout: 5_000 })
    await page.getByText('危险命令需要确认', { exact: false }).first().waitFor({ state: 'visible', timeout: 5_000 })

    const optionCount = await page.locator('.decision-option').count()
    if (optionCount < 3) {
      throw new Error(`Expected three approval options, saw ${optionCount}`)
    }

    const clickAt = performance.now()
    await page.locator('.decision-option').nth(0).click()
    await page.locator('.decision-card-status').filter({ hasText: '处理中' }).first().waitFor({ state: 'visible', timeout: 500 })
    const lockedVisibleMs = elapsed(clickAt)
    if (lockedVisibleMs > 100) {
      throw new Error(`Approval lock exceeded 100ms: ${lockedVisibleMs}ms`)
    }
    await expandProcess(page)
    await page.locator('.decision-card-decision').filter({ hasText: '已选择' }).first().waitFor({ state: 'visible', timeout: 700 })
    const resolvedVisibleMs = elapsed(clickAt)
    if (resolvedVisibleMs > 700) {
      throw new Error(`Approval resolved visibility exceeded 700ms: ${resolvedVisibleMs}ms`)
    }
    const remainingOptions = await page.locator('.decision-option').count()
    if (remainingOptions !== 0) {
      throw new Error(`Expected approval options to be locked after decision, saw ${remainingOptions}`)
    }

    await page.reload({ waitUntil: 'networkidle' })
    await page.locator('textarea[placeholder="输入任务描述..."]').first().waitFor({ state: 'visible', timeout: 15_000 })
    await expandProcess(page)
    await page.locator('.decision-card-decision').filter({ hasText: '已选择' }).first().waitFor({ state: 'visible', timeout: 5_000 })

    if (appServerSockets.length < 1) throw new Error('Expected at least one /api/app-server WebSocket connection')
    if (forbiddenRequests.length) {
      throw new Error(`Forbidden legacy realtime requests observed:\n${forbiddenRequests.join('\n')}`)
    }
    if (failedRequests.some((item) => !item.includes('/favicon'))) {
      throw new Error(`Network request failures observed:\n${failedRequests.join('\n')}`)
    }
    if (badResponses.length) {
      throw new Error(`Bad HTTP responses observed:\n${badResponses.join('\n')}`)
    }
    if (consoleErrors.length) {
      throw new Error(`Browser console errors observed:\n${consoleErrors.join('\n')}`)
    }

    console.log(JSON.stringify({
      session_id: session.id,
      request_id: requestId,
      locked_visible_ms: lockedVisibleMs,
      resolved_visible_ms: resolvedVisibleMs,
      app_server_socket_count: appServerSockets.length,
      forbidden_request_count: forbiddenRequests.length,
    }, null, 2))
  } catch (error) {
    await writeDiagnostics(page, session.id, 'approval-e2e-failure', {
      appServerSockets,
      forbiddenRequests,
      failedRequests,
      badResponses,
      consoleErrors,
      error: String(error),
    })
    throw error
  } finally {
    await browser.close()
  }
}

async function expandProcess(page) {
  await page.getByText('查看过程', { exact: false }).first().click({ timeout: 500 }).catch(() => undefined)
}

async function writeDiagnostics(page, sessionId, label, details = {}) {
  const fs = await import('node:fs/promises')
  const safe = `${label}-${sessionId}`
  await page.screenshot({ path: new URL(`${safe}.png`, artifactDir), fullPage: true }).catch(() => undefined)
  const bodyText = await page.locator('body').innerText({ timeout: 1_000 }).catch((error) => String(error))
  const html = await page.content().catch((error) => String(error))
  await fs.writeFile(new URL(`${safe}.txt`, artifactDir), bodyText, 'utf8')
  await fs.writeFile(new URL(`${safe}.html`, artifactDir), html, 'utf8')
  await fs.writeFile(new URL(`${safe}.json`, artifactDir), JSON.stringify(details, null, 2), 'utf8')
}

main().catch((error) => {
  console.error(error.stack || error.message)
  process.exit(1)
})
