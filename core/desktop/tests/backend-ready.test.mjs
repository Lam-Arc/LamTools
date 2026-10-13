import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const source = readFileSync(new URL('../src/backendReady.ts', import.meta.url), 'utf8')
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { waitForBackendApiBase } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`)

test('late backend readiness succeeds instead of permanent plugin failure', async () => {
  let calls = 0
  const result = await waitForBackendApiBase(async () => {
    if (++calls < 3) throw 'backend not yet started'
    return 'http://127.0.0.1:53798'
  }, { attempts: 3, delayMs: 0 })
  assert.equal(result, 'http://127.0.0.1:53798')
  assert.equal(calls, 3)
})
test('real startup failure is not retried or swallowed', async () => {
  let calls = 0
  await assert.rejects(waitForBackendApiBase(async () => {
    calls++
    throw new Error('Python failed')
  }, { attempts: 3, delayMs: 0 }), /Python failed/)
  assert.equal(calls, 1)
})
test('readiness waiting is bounded', async () => {
  let calls = 0
  await assert.rejects(waitForBackendApiBase(async () => {
    calls++
    throw 'backend not yet started'
  }, { attempts: 2, delayMs: 0 }), /启动超时/)
  assert.equal(calls, 2)
})
test('closing host cancels waiting without another request', async () => {
  const controller = new AbortController()
  let calls = 0
  const waiting = waitForBackendApiBase(async () => {
    calls++
    throw 'backend not yet started'
  }, { signal: controller.signal, delayMs: 10000 })
  await new Promise(resolve => setImmediate(resolve))
  controller.abort()
  await assert.rejects(waiting, { name: 'AbortError' })
  assert.equal(calls, 1)
})
test('invalid addresses fail immediately', async () => {
  await assert.rejects(waitForBackendApiBase(async () => 'https://remote.example'), /地址无效/)
})
