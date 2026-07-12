import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewSource = readFileSync(resolve('src/views/SettingsView.vue'), 'utf8')

test('Writer delegates its complete settings surface to CoreSettings', () => {
  assert.match(viewSource, /import\s*\{[\s\S]*?CoreSettings[\s\S]*?\}\s*from '@lamtools\/ui'/)
  assert.match(viewSource, /<CoreSettings/)
  assert.match(viewSource, /:models="configStore\.models"/)
  assert.match(viewSource, /:providers="configStore\.providers"/)
  assert.match(viewSource, /:command-policies="commandPolicies"/)
  assert.doesNotMatch(viewSource, /<SettingsShell/)
  assert.doesNotMatch(viewSource, /<ThemeEditor/)
})

test('Writer keeps only adapters for shared settings operations', () => {
  assert.match(viewSource, /@create-provider="createProvider"/)
  assert.match(viewSource, /@create-model="createModel"/)
  assert.match(viewSource, /@update-command-policy="updateCommandPolicy"/)
  assert.match(viewSource, /PROVIDER_PRESETS/)
  assert.match(viewSource, /UI_NAMESPACE = 'lamwriter\.ui'/)
  assert.ok(viewSource.split('\n').length < 260)
})
