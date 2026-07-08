import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewSource = readFileSync(resolve('src/views/CoreWorkbenchView.vue'), 'utf8')

test('runtime resource widget combines context and call stats in one right-panel block', () => {
  assert.match(viewSource, /class="[^"]*runtime-resource-widget[^"]*"/)
  assert.match(viewSource, />资源</)
  assert.doesNotMatch(viewSource, />上下文统计</)
  assert.doesNotMatch(viewSource, />调用统计</)
  assert.doesNotMatch(viewSource, /data-action="demo-update"/)
})

test('runtime resource widget renders waterline motion and hover hint', () => {
  assert.match(viewSource, /runtimeResourceSummary/)
  assert.match(viewSource, /--runtime-resource-used/)
  assert.match(viewSource, /class="runtime-resource-bar"/)
  assert.match(viewSource, /当前\s+\{\{\s*runtimeResourceSummary\.currentPct\s*\}\}%\s+·\s+\{\{\s*runtimeResourceSummary\.thresholdPct\s*\}\}%\s+后自动压缩/)
  assert.match(viewSource, /\.runtime-resource-used\s*\{[^}]*transition:\s*transform 180ms/s)
  assert.match(viewSource, /\.runtime-resource-values\s+strong\s*\{[^}]*transition:\s*opacity 120ms/s)
  assert.match(viewSource, /prefers-reduced-motion:\s*reduce/)
})

test('runtime resource widget does not treat cumulative token usage as current context', () => {
  const contextStats = viewSource.match(/const contextResourceStats = computed\(\(\) => \{[\s\S]*?\n\}\)/)?.[0] || ''

  assert.match(contextStats, /metrics\.estimated_prompt_tokens/)
  assert.match(contextStats, /metrics\.context_window_tokens/)
  assert.doesNotMatch(contextStats, /metrics\.input_tokens/)
  assert.doesNotMatch(contextStats, /metrics\.prompt_tokens/)
})

test('runtime resource widget separates over-threshold state from completed compaction', () => {
  const resourceSummary = viewSource.match(/const runtimeResourceSummary = computed\(\(\) => \{[\s\S]*?\n\}\)/)?.[0] || ''

  assert.match(resourceSummary, /contextCompacted/)
  assert.match(resourceSummary, /'已压缩'/)
  assert.match(resourceSummary, /'需压缩'/)
  assert.doesNotMatch(resourceSummary, /currentPct >= thresholdPct \? '已压缩'/)
})
