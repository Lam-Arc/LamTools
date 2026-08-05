import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewSource = readFileSync(resolve('src/views/CoreWorkbenchView.vue'), 'utf8')

test('session rename entry lives in the active thread title, not the sidebar', () => {
  assert.doesNotMatch(viewSource, /allow-rename/)
  assert.doesNotMatch(viewSource, /@rename-session="handleRenameSession"/)
  assert.match(viewSource, /<CoreSessionTitleEditor/)
  assert.match(viewSource, /:rename="renameActiveSession"/)
  assert.doesNotMatch(viewSource, /session-title-input/)
  assert.doesNotMatch(viewSource, /submitActiveSessionTitle/)
})
