import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewSource = readFileSync(resolve('src/views/CoreWorkbenchView.vue'), 'utf8')

test('Writer delegates generic project UI to Core', () => {
  assert.match(viewSource, /CoreProjectCreate/)
  assert.match(viewSource, /CoreAgentsEditor/)
  assert.doesNotMatch(viewSource, /class="new-project-popover"/)
  assert.doesNotMatch(viewSource, /class="agents-editor"/)
})
