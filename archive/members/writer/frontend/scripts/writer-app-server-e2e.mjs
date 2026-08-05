import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'

const frontendUrl = process.env.WRITER_FRONTEND_URL || 'http://127.0.0.1:6174'
const backendUrl = process.env.WRITER_BACKEND_URL || 'http://127.0.0.1:6173'
const headless = process.env.HEADLESS !== '0'
const runId = new Date().toISOString().replace(/[:.]/g, '-')
const firstText = `app-server-e2e accepted ${runId}`
const secondText = `app-server-e2e queued ${runId}`
const artifactDir = new URL('../../../../tmp/writer-app-server-e2e/', import.meta.url)
const workRoot = new URL(`../../../../tmp/writer-app-server-e2e/workspaces/basic-${runId}/`, import.meta.url)
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
      title: `App Server E2E ${runId}`,
      work_root: workRootPath,
    }),
  })
}

async function interruptSession(threadId) {
  const wsUrl = new URL('/api/app-server', backendUrl)
  wsUrl.protocol = wsUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  await new Promise((resolve, reject) => {
    const socket = new WebSocket(wsUrl)
    const timeout = setTimeout(() => {
      try {
        socket.close()
      } catch {
        // ignore close errors
      }
      reject(new Error('Timed out interrupting app-server session'))
    }, 5_000)
    socket.onopen = () => {
      socket.send(JSON.stringify({
        id: 1,
        method: 'initialize',
        params: { clientInfo: { name: 'writer_app_server_e2e', version: '0.1.0' }, threadId },
      }))
    }
    socket.onmessage = (message) => {
      const payload = JSON.parse(message.data)
      if (payload.id === 1) {
        socket.send(JSON.stringify({
          id: 2,
          method: 'turn/interrupt',
          params: { thread_id: threadId },
        }))
      }
      if (payload.id === 2) {
        clearTimeout(timeout)
        socket.close()
        resolve()
      }
    }
    socket.onerror = () => {
      clearTimeout(timeout)
      reject(new Error('Failed to interrupt app-server session'))
    }
  })
}

function elapsed(startedAt) {
  return Math.round(performance.now() - startedAt)
}

async function main() {
  const session = await createSession()
  const browser = await chromium.launch({ headless })
  const page = await browser.newPage()
  const consoleErrors = []
  const failedRequests = []
  const badResponses = []
  const forbiddenRequests = []
  const appServerSockets = []

  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text())
    }
  })
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message)
  })
  page.on('request', (request) => {
    const url = request.url()
    if (forbiddenRequestPatterns.some((pattern) => pattern.test(url))) {
      forbiddenRequests.push(url)
    }
  })
  page.on('requestfailed', (request) => {
    const failureText = request.failure()?.errorText || ''
    const url = request.url()
    if (
      request.method() === 'GET'
      && new URL(url).pathname === '/api/core/sessions'
      && failureText === 'net::ERR_ABORTED'
    ) {
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
    if (socket.url().includes('/api/app-server')) {
      appServerSockets.push(socket.url())
    }
  })

  try {
    await import('node:fs/promises').then((fs) => fs.mkdir(artifactDir, { recursive: true }))
    await page.goto(`${frontendUrl}/?session=${encodeURIComponent(session.id)}`, { waitUntil: 'networkidle' })
    const composer = page.locator('textarea[placeholder="输入任务描述..."]').first()
    await composer.waitFor({ state: 'visible', timeout: 15_000 })

    const submitAt = performance.now()
    await composer.fill(firstText)
    await page.locator('button.send:not([disabled])').waitFor({ state: 'visible', timeout: 2_000 })
    await page.locator('button.send').click()
    await page.getByText(firstText, { exact: false }).first().waitFor({ state: 'visible', timeout: 5_000 }).catch(async (error) => {
      await writeDiagnostics(page, session.id, 'accepted-timeout', {
        appServerSockets,
        forbiddenRequests,
        failedRequests,
        badResponses,
        consoleErrors,
      })
      throw error
    })
    const acceptedVisibleMs = elapsed(submitAt)
    if (acceptedVisibleMs > 300) {
      throw new Error(`Accepted visibility exceeded 300ms: ${acceptedVisibleMs}ms`)
    }

    const secondSubmitAt = performance.now()
    await composer.fill(secondText)
    await page.locator('button.send:not([disabled])').waitFor({ state: 'visible', timeout: 2_000 })
    await page.locator('button.send').click()
    const queuedVisible = await page.locator('.queued-input-tray').getByText(secondText, { exact: false }).first().waitFor({
      state: 'visible',
      timeout: 1_500,
    }).then(() => true, () => false)
    const secondVisibleMs = queuedVisible ? elapsed(secondSubmitAt) : null
    if (secondVisibleMs !== null && secondVisibleMs > 300) {
      throw new Error(`Queued visibility exceeded 300ms: ${secondVisibleMs}ms`)
    }

    await page.reload({ waitUntil: 'networkidle' })
    await composer.waitFor({ state: 'visible', timeout: 15_000 })
    await page.getByText(firstText, { exact: false }).first().waitFor({ state: 'visible', timeout: 5_000 })
    if (queuedVisible) {
      await page.locator('.queued-input-tray').getByText(secondText, { exact: false }).first().waitFor({ state: 'visible', timeout: 5_000 })
    }

    if (appServerSockets.length < 1) {
      await writeDiagnostics(page, session.id, 'missing-websocket', {
        appServerSockets,
        forbiddenRequests,
        failedRequests,
        badResponses,
        consoleErrors,
      })
      throw new Error('Expected at least one /api/app-server WebSocket connection')
    }
    const uniqueSockets = new Set(appServerSockets)
    if (uniqueSockets.size > 2) {
      throw new Error(`Expected one active app-server socket per page lifecycle; saw ${[...uniqueSockets].join(', ')}`)
    }
    if (forbiddenRequests.length) {
      await writeDiagnostics(page, session.id, 'forbidden-requests', {
        appServerSockets,
        forbiddenRequests,
        failedRequests,
        consoleErrors,
      })
      throw new Error(`Forbidden legacy realtime requests observed:\n${forbiddenRequests.join('\n')}`)
    }
    if (failedRequests.some((item) => !item.includes('/favicon'))) {
      await writeDiagnostics(page, session.id, 'request-failures', {
        appServerSockets,
        forbiddenRequests,
        failedRequests,
        badResponses,
        consoleErrors,
      })
      throw new Error(`Network request failures observed:\n${failedRequests.join('\n')}`)
    }
    if (badResponses.length) {
      await writeDiagnostics(page, session.id, 'bad-responses', {
        appServerSockets,
        forbiddenRequests,
        failedRequests,
        badResponses,
        consoleErrors,
      })
      throw new Error(`Bad HTTP responses observed:\n${badResponses.join('\n')}`)
    }
    if (consoleErrors.length) {
      await writeDiagnostics(page, session.id, 'console-errors', {
        appServerSockets,
        forbiddenRequests,
        failedRequests,
        badResponses,
        consoleErrors,
      })
      throw new Error(`Browser console errors observed:\n${consoleErrors.join('\n')}`)
    }

    await interruptSession(session.id).catch((error) => {
      console.warn(`cleanup interrupt failed: ${error.message}`)
    })

    const result = {
      session_id: session.id,
      accepted_visible_ms: acceptedVisibleMs,
      queued_visible_ms: secondVisibleMs,
      queued_observed: queuedVisible,
      app_server_socket_count: appServerSockets.length,
      forbidden_request_count: forbiddenRequests.length,
    }
    console.log(JSON.stringify(result, null, 2))
  } finally {
    await browser.close()
  }
}

async function writeDiagnostics(page, sessionId, label, details = {}) {
  const fs = await import('node:fs/promises')
  const safe = `${label}-${sessionId}`
  await page.screenshot({ path: new URL(`${safe}.png`, artifactDir), fullPage: true }).catch(() => undefined)
  const bodyText = await page.locator('body').innerText({ timeout: 1_000 }).catch((error) => String(error))
  const html = await page.content().catch((error) => String(error))
  const runtime = await page.evaluate(() => ({
    textareas: [...document.querySelectorAll('textarea')].map((item) => ({
      placeholder: item.getAttribute('placeholder'),
      value: item.value,
      disabled: item.disabled,
    })),
    sendButtons: [...document.querySelectorAll('button.send')].map((item) => ({
      text: item.textContent,
      disabled: item.disabled,
      ariaLabel: item.getAttribute('aria-label'),
    })),
  })).catch((error) => ({ error: String(error) }))
  await fs.writeFile(new URL(`${safe}.txt`, artifactDir), bodyText, 'utf8')
  await fs.writeFile(new URL(`${safe}.html`, artifactDir), html, 'utf8')
  await fs.writeFile(new URL(`${safe}.json`, artifactDir), JSON.stringify({ ...details, runtime }, null, 2), 'utf8')
}

main().catch((error) => {
  console.error(error.stack || error.message)
  process.exit(1)
})
