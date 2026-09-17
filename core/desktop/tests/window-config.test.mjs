import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const config = JSON.parse(
  readFileSync(new URL('../src-tauri/tauri.conf.json', import.meta.url), 'utf8'),
)

test('main window lets the responsive workspace own its width', () => {
  const mainWindow = config.app.windows.find((window) => window.label !== 'desktop-plugin-host')

  assert.ok(mainWindow)
  assert.equal('minWidth' in mainWindow, false)
})
