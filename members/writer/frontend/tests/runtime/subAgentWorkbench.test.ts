import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewSource = readFileSync(resolve('src/views/CoreWorkbenchView.vue'), 'utf8')
const storeSource = readFileSync(resolve('src/appServer/store.ts'), 'utf8')

test('Writer mounts the shared Sub Agent panel between resources and runtime progress', () => {
  assert.match(
    viewSource,
    /#right-panel[\s\S]*CoreResourceStats[\s\S]*CoreSubAgentPanel[\s\S]*RuntimePanel/,
  )
  assert.match(viewSource, /:runs="subAgentRuns"/)
  assert.match(viewSource, /@open="openSubAgent"/)
})

test('Writer keeps active and recently updated Sub Agents inside the four-row preview', () => {
  assert.match(viewSource, /\.sort\(\(left, right\) => compareSubAgentRuns\(left, right, agentIndexById\)\)/)
  assert.match(viewSource, /function subAgentDisplayRank[\s\S]*status === 'running'[\s\S]*status === 'pending'/)
  assert.match(viewSource, /return rightUpdatedAt - leftUpdatedAt/)
  assert.match(viewSource, /return rightIndex - leftIndex/)
})

test('Writer mounts the shared Sub Agent dialog with isolated controls and submit path', () => {
  assert.match(viewSource, /<CoreSubAgentDialog/)
  assert.match(viewSource, /v-model:draft="subAgentDraft"/)
  assert.match(viewSource, /:disabled="subAgentInputDisabled"/)
  assert.match(viewSource, /subAgentSubmitDisabled[\s\S]*!subAgentDraft\.value\.trim\(\)/)
  assert.match(viewSource, /:selected-model-id="subAgentSelectedModelId"/)
  assert.match(viewSource, /@submit="sendSubAgentMessage"/)
  assert.match(viewSource, /appServerStore\.listSubAgents/)
  assert.match(viewSource, /appServerStore\.getSubAgent/)
  assert.match(viewSource, /appServerStore\.startSubAgentTurn/)
  assert.doesNotMatch(viewSource, /routes\.sub_agent/)
})

test('Writer exposes Sub Agent App Server operations without opening a child socket', () => {
  assert.match(storeSource, /client\.request\('sub_agent\.list'/)
  assert.match(storeSource, /client\.request\('sub_agent\.get'/)
  assert.match(storeSource, /client\.request\('sub_agent\.turn\.start'/)
  assert.doesNotMatch(storeSource, /connect\([^\n]*subSessionId/)
})
