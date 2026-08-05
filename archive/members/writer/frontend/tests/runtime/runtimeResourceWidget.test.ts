import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewSource = readFileSync(resolve('src/views/CoreWorkbenchView.vue'), 'utf8')
const coreComponentSource = readFileSync(resolve('../../../core/ui/src/components/CoreResourceStats.vue'), 'utf8')
const coreResourceSource = readFileSync(resolve('../../../core/ui/src/runtime/resources.ts'), 'utf8')

test('Writer delegates panel and composer resource statistics to Core', () => {
  assert.match(viewSource, /CoreResourceStats/)
  assert.match(viewSource, /#composer-status/)
  assert.match(viewSource, /variant="composer"/)
  assert.match(viewSource, /#right-panel[\s\S]*CoreResourceStats/)
  assert.doesNotMatch(viewSource, /runtimeResourceSummary|contextResourceStats|runtime-resource-widget/)
})

test('Core owns the shared resource panel and composer percentage line', () => {
  assert.match(coreComponentSource, /class="runtime-widget core-resource-widget"/)
  assert.match(coreComponentSource, /class="core-resource-line"/)
  assert.match(coreComponentSource, /role="meter"/)
  assert.match(coreComponentSource, /prefers-reduced-motion:\s*reduce/)
})

test('Core context usage excludes cumulative input and output totals', () => {
  const contextMetrics = coreResourceSource.match(/for \(const message of messages\) \{[\s\S]*?if \(records\.length === 0 && current < 0\) return null/)?.[0] || ''
  assert.match(contextMetrics, /record\.estimated_prompt_tokens/)
  assert.match(contextMetrics, /record\.context_tokens/)
  assert.doesNotMatch(contextMetrics, /record\.(?:input_tokens|prompt_tokens)\b/)
})

test('Core separates over-threshold state from completed compaction', () => {
  assert.match(coreResourceSource, /contextCompacted/)
  assert.match(coreResourceSource, /'已压缩'/)
  assert.match(coreResourceSource, /'需压缩'/)
  assert.doesNotMatch(coreResourceSource, /currentPct >= thresholdPct \? '已压缩'/)
})
