import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'

const frontendUrl = process.env.WRITER_FRONTEND_URL || 'http://127.0.0.1:6174'
const backendUrl = process.env.WRITER_BACKEND_URL || 'http://127.0.0.1:6173'
const headless = process.env.HEADLESS !== '0'
const runId = new Date().toISOString().replace(/[:.]/g, '-')
const artifactDir = new URL('../../../../tmp/writer-app-server-e2e/', import.meta.url)
const resultPath = new URL(`long-context-${runId}.json`, artifactDir)
const workRoot = new URL(`../../../../tmp/writer-app-server-e2e/workspaces/long-context-${runId}/`, import.meta.url)
const workRootPath = fileURLToPath(workRoot)
const observeMs = Number.parseInt(process.env.LONG_CONTEXT_OBSERVE_MS || '30000', 10)

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
  if (!response.ok) throw new Error(`${options.method || 'GET'} ${url} failed ${response.status}: ${text.slice(0, 500)}`)
  return text ? JSON.parse(text) : null
}

async function createSession() {
  await import('node:fs/promises').then((fs) => fs.mkdir(workRoot, { recursive: true }))
  return requestJson(`${backendUrl}/api/core/sessions`, {
    method: 'POST',
    body: JSON.stringify({
      title: `App Server Long Context E2E ${runId}`,
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
      try { socket.close() } catch {}
      reject(new Error('Timed out interrupting app-server session'))
    }, 5_000)
    socket.onopen = () => {
      socket.send(JSON.stringify({
        id: 1,
        method: 'initialize',
        params: { clientInfo: { name: 'writer_long_context_e2e', version: '0.1.0' }, threadId },
      }))
    }
    socket.onmessage = (message) => {
      const payload = JSON.parse(message.data)
      if (payload.id === 1) {
        socket.send(JSON.stringify({ id: 2, method: 'turn/interrupt', params: { thread_id: threadId } }))
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

function longPrompt() {
  const block = '背景材料：Writer 需要在长上下文下保持发送反馈迅速，不能让用户输入等待数据库轮询或旧 SSE 投影。'
  return [
    `long-context-app-server ${runId}`,
    block.repeat(260),
    '请只用 80 个中文以内回答：实时链路整改后，为什么点击发送应该立即出现 accepted 事实？不要使用工具。',
  ].join('\n')
}

async function main() {
  const session = await createSession()
  const browser = await chromium.launch({ headless })
  const page = await browser.newPage()
  const failedRequests = []
  const forbiddenRequests = []
  const consoleErrors = []
  const appServerEvents = []

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
    if (request.method() === 'GET' && failureText === 'net::ERR_ABORTED' && isNavigationAbortPath(new URL(url).pathname)) return
    failedRequests.push(`${request.method()} ${url} ${failureText}`)
  })
  page.on('websocket', (socket) => {
    if (!socket.url().includes('/api/app-server')) return
    socket.on('framereceived', (frame) => {
      try {
        const message = JSON.parse(String(frame.payload))
        if (message.method && message.params) {
          const payload = message.params.payload
          appServerEvents.push({
            at_ms: Math.round(performance.now()),
            method: message.method,
            event_method: message.params.method,
            run_item_kind: payload?.kind,
            payload_type: payload?.payload?.type || payload?.type,
          })
        }
      } catch {
        // ignore non-json frames
      }
    })
  })

  const result = {
    session_id: session.id,
    run_id: runId,
    prompt_chars: 0,
    accepted_visible_ms: null,
    first_non_user_item_event_ms: null,
    first_agent_message_event_ms: null,
    provider_message_observed: false,
    observe_ms: observeMs,
    forbidden_request_count: 0,
    failed_requests: [],
    console_errors: [],
  }

  try {
    await import('node:fs/promises').then((fs) => fs.mkdir(artifactDir, { recursive: true }))
    await page.goto(`${frontendUrl}/?session=${encodeURIComponent(session.id)}`, { waitUntil: 'networkidle' })
    const composer = page.locator('textarea[placeholder="输入任务描述..."]').first()
    await composer.waitFor({ state: 'visible', timeout: 15_000 })

    const prompt = longPrompt()
    result.prompt_chars = prompt.length
    const submitAt = performance.now()
    await composer.fill(prompt)
    await page.locator('button.send:not([disabled])').waitFor({ state: 'visible', timeout: 2_000 })
    await page.locator('button.send').click()
    await page.getByText(`long-context-app-server ${runId}`, { exact: false }).first().waitFor({ state: 'visible', timeout: 5_000 })
    result.accepted_visible_ms = elapsed(submitAt)
    if (result.accepted_visible_ms > 300) throw new Error(`Accepted visibility exceeded 300ms: ${result.accepted_visible_ms}ms`)

    const deadline = performance.now() + observeMs
    while (performance.now() < deadline) {
      const nonUser = appServerEvents.find((event) => event.event_method === 'core/runItem' && event.run_item_kind && !['usage', 'status'].includes(event.run_item_kind))
      const message = appServerEvents.find((event) => event.event_method === 'core/runItem' && event.run_item_kind === 'message' && event.payload_type === 'agentMessage')
      if (nonUser && result.first_non_user_item_event_ms === null) result.first_non_user_item_event_ms = Math.round(nonUser.at_ms - submitAt)
      if (message && result.first_agent_message_event_ms === null) {
        result.first_agent_message_event_ms = Math.round(message.at_ms - submitAt)
        result.provider_message_observed = true
        break
      }
      await page.waitForTimeout(100)
    }

    result.forbidden_request_count = forbiddenRequests.length
    result.failed_requests = failedRequests
    result.console_errors = consoleErrors
    if (forbiddenRequests.length) throw new Error(`Forbidden legacy realtime requests observed:\n${forbiddenRequests.join('\n')}`)
    if (failedRequests.some((item) => !item.includes('/favicon'))) throw new Error(`Network request failures observed:\n${failedRequests.join('\n')}`)
    if (consoleErrors.length) throw new Error(`Browser console errors observed:\n${consoleErrors.join('\n')}`)
  } finally {
    await interruptSession(session.id).catch(() => undefined)
    await import('node:fs/promises').then((fs) => fs.writeFile(resultPath, JSON.stringify(result, null, 2), 'utf8')).catch(() => undefined)
    await browser.close()
  }
  console.log(JSON.stringify({ ...result, result_path: resultPath.pathname }, null, 2))
}

function isNavigationAbortPath(pathname) {
  return pathname === '/api/core/sessions'
    || /^\/api\/sessions\/[^/]+\/changes$/.test(pathname)
    || /^\/api\/sessions\/[^/]+\/agent-branches$/.test(pathname)
}

main().catch((error) => {
  console.error(error.stack || error.message)
  process.exit(1)
})
