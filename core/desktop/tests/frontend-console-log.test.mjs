import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

// user:“修”+(通过真实 console→写入通道验证对象和循环引用都能留存。)
const source = readFileSync(new URL('../src/frontendConsoleLog.ts', import.meta.url), 'utf8')

function logger() {
  const batches = []
  const listeners = {}
  let flush
  const context = vm.createContext({
    console: Object.fromEntries(['log', 'info', 'warn', 'error', 'debug', 'trace'].map(level => [level, () => {}])),
    window: { addEventListener: (name, callback) => { listeners[name] = callback } },
    setTimeout: callback => { flush = callback; return 1 },
    invoke: async (_command, payload) => { batches.push(payload.lines) },
  })
  const js = ts.transpileModule(source
    .replace(/^import .* from '@tauri-apps\/api\/core'\s*$/m, '')
    .replace(/import\.meta/g, '({ env: { DEV: true } })')
    .replace('export function installFrontendConsoleLog', 'function installFrontendConsoleLog'),
  { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  vm.runInContext(js, context)
  return { context, batches, flush: () => flush() }
}

test('ordinary console objects and arrays retain their fields', () => {
  const log = logger()
  vm.runInContext('console.error({ status: 500, details: { message: "failed" } }, [1, { ok: true }])', log.context)
  log.flush()
  assert.match(log.batches.join('\n'), /\{"status":500,"details":\{"message":"failed"\}\}/)
  assert.match(log.batches.join('\n'), /\[1,\{"ok":true\}\]/)
})

test('circular references stay bounded while adjacent fields survive', () => {
  const log = logger()
  vm.runInContext('const value = { status: 500 }; value.self = value; console.error(value)', log.context)
  log.flush()
  assert.match(log.batches.join('\n'), /\{"status":500,"self":"\[Circular\]"\}/)
})
