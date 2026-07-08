import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewSource = readFileSync(resolve('src/views/CoreWorkbenchView.vue'), 'utf8')

test('session rename entry lives in the active thread title, not the sidebar', () => {
  assert.match(viewSource, /:allow-rename="false"/)
  assert.doesNotMatch(viewSource, /@rename-session="handleRenameSession"/)
  assert.match(viewSource, /class="session-title-input"/)
  assert.doesNotMatch(viewSource, /class="session-title-display"/)
  assert.doesNotMatch(viewSource, /beginActiveSessionTitleEdit/)
  assert.doesNotMatch(viewSource, /\.select\(\)/)
  assert.match(viewSource, /@blur="submitActiveSessionTitle"/)
  assert.match(viewSource, /@focus="handleActiveSessionTitleFocus"/)
  assert.match(viewSource, /@input="handleActiveSessionTitleInput"/)
  assert.match(viewSource, /@keydown\.enter\.prevent="submitActiveSessionTitle"/)
  assert.match(viewSource, /@keydown\.esc\.prevent="cancelActiveSessionTitleEdit"/)
  assert.match(viewSource, /\.session-title-input\s*\{[^}]*width: 100%;/s)
  assert.match(viewSource, /\.session-title-input\s*\{[^}]*border: 0;/s)
  assert.doesNotMatch(viewSource, /\.session-title-input:focus\s*\{[^}]*box-shadow:/s)
})
