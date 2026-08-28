import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

const logicSource = await readFile(new URL('../../src/lamtools_core/plugins/bundled/emotion-ball-pet/desktop/petLogic.js', import.meta.url), 'utf8')
const petSource = await readFile(new URL('../../src/lamtools_core/plugins/bundled/emotion-ball-pet/desktop/pet.js', import.meta.url), 'utf8')
const hostSource = await readFile(new URL('../src/desktopPluginHost.ts', import.meta.url), 'utf8')
const context = { window: {} }
context.globalThis = context
vm.runInNewContext(logicSource, context, { filename: 'petLogic.js' })
const logic = context.window.EmotionBallPetLogic

test('exposes the fixed card priority ordering', () => {
  assert.equal(logic.cardPriority({ kind: 'approval' }), 100)
  assert.equal(logic.cardPriority({ kind: 'question' }), 90)
  assert.equal(logic.cardPriority({ kind: 'file' }), 80)
  assert.equal(logic.cardPriority({ kind: 'info' }), 10)
  assert.equal(logic.cardPriority({ kind: 'unknown' }), 0)
})

test('replaces lower priority cards and reports suspended cards', () => {
  assert.equal(JSON.stringify(logic.cardReplacement({ kind: 'file' }, { kind: 'approval' })), JSON.stringify({ replace: true, suspend: true, defer: false }))
  assert.equal(JSON.stringify(logic.cardReplacement({ kind: 'approval' }, { kind: 'success' })), JSON.stringify({ replace: false, suspend: false, defer: false }))
  assert.equal(JSON.stringify(logic.cardReplacement({ kind: 'reply' }, { kind: 'reply' })), JSON.stringify({ replace: true, suspend: false, defer: false }))
})

test('defers file cards that arrive while an interaction card is active', () => {
  assert.equal(JSON.stringify(logic.cardReplacement({ kind: 'approval' }, { kind: 'file' })), JSON.stringify({ replace: false, suspend: false, defer: true }))
  assert.equal(JSON.stringify(logic.cardReplacement({ kind: 'question' }, { kind: 'file' })), JSON.stringify({ replace: false, suspend: false, defer: true }))
})

test('normalizes dropped file names and preserves source indexes', () => {
  assert.equal(JSON.stringify(logic.normalizeDroppedFiles([
    { path: 'C:\\reports\\report.pdf' },
    { path: '/tmp/notes.txt', name: 'notes.txt', index: 7 },
    { path: '  ' },
    null
  ], ' drop-1 ')), JSON.stringify([
    { name: 'report.pdf', index: 0, dropId: 'drop-1' },
    { name: 'notes.txt', index: 7, dropId: 'drop-1' }
  ]))
})

test('checks imported files by their original source indexes', () => {
  const imported = [
    { dataBase64: 'first' },
    { dataBase64: 'second' },
  ]
  assert.equal(logic.pendingSourcesReady([{ index: 1 }], imported), true)
  assert.equal(logic.pendingSourcesReady([{ index: 1 }], [imported[1]]), false)
  assert.equal(logic.pendingSourcesReady([{ index: 8, attachment: { id: 'uploaded' } }], []), true)
})

test('keeps a restored card open after an interaction is cleared', () => {
  assert.equal(logic.shouldCollapseAfterInteraction(true, true, 'card'), false)
  assert.equal(logic.shouldCollapseAfterInteraction(true, false, 'card'), true)
  assert.equal(logic.shouldCollapseAfterInteraction(true, false, 'pet'), false)
})

test('summarizes replies to four non-empty lines and a bounded length', () => {
  assert.equal(logic.replySummary('  first\n\n second \nthird\nfourth\nfifth'), 'first\nsecond\nthird\nfourth')
  assert.equal(logic.replySummary(''), 'Agent 已完成回答。')
  assert.equal(logic.replySummary('x'.repeat(400)).length, 358)
  assert.equal(logic.replySummary('x'.repeat(400)).endsWith('…'), true)
})

test('promotes only cards carrying full detail into panel content', () => {
  assert.equal(logic.panelDetailFromCard({ title: '摘要', body: '短内容' }), null)
  assert.equal(JSON.stringify(logic.panelDetailFromCard({
    kind: 'reply',
    title: 'Agent 回复',
    body: '摘要',
    detailBody: '完整回复'
  })), JSON.stringify({ title: 'Agent 回复', body: '完整回复', tone: 'reply' }))
  assert.equal(JSON.stringify(logic.panelDetailFromCard({
    kind: 'error',
    title: '处理失败',
    detailTitle: '错误详情',
    detailBody: '完整错误'
  })), JSON.stringify({ title: '错误详情', body: '完整错误', tone: 'error' }))
})

test('reports every visible surface as expanded to assistive technology', () => {
  assert.equal(JSON.stringify(logic.petToggleAccessibility('pet')), JSON.stringify({
    expanded: false,
    label: '打开桌宠面板'
  }))
  assert.equal(JSON.stringify(logic.petToggleAccessibility('card')), JSON.stringify({
    expanded: true,
    label: '打开桌宠面板'
  }))
  assert.equal(JSON.stringify(logic.petToggleAccessibility('panel')), JSON.stringify({
    expanded: true,
    label: '收起桌宠面板'
  }))
})

test('generic UI errors do not overwrite the active run state', () => {
  const showErrorSource = petSource.match(/function showError[\s\S]*?\n  function sendSocket/)?.[0] || ''
  assert.notEqual(showErrorSource, '')
  assert.doesNotMatch(showErrorSource, /state\.running\s*=/)
  assert.match(petSource, /kind === 'error'\) \{\s+state\.running = false/)
})

test('approval responses are guarded against duplicate submission', () => {
  const respondSource = petSource.match(/async function respondApproval[\s\S]*?\n  elements\.petToggle/)?.[0] || ''
  assert.notEqual(respondSource, '')
  assert.match(respondSource, /if \(!state\.interaction \|\| state\.interactionResponseInFlight\) return/)
  assert.match(respondSource, /state\.interactionResponseInFlight = true/)
  assert.match(respondSource, /finally \{\s+state\.interactionResponseInFlight = false/)
})

test('keeps interaction context while appending a retryable submission error', () => {
  assert.equal(logic.interactionBodyWithError('允许执行命令吗？', ''), '允许执行命令吗？')
  assert.equal(
    logic.interactionBodyWithError('允许执行命令吗？', '  请求超时  '),
    '允许执行命令吗？\n\n提交失败：请求超时'
  )
})

test('desktop host selects the pet by identity instead of registry order', () => {
  assert.match(hostSource, /DESKTOP_PET_PLUGIN_NAME = 'emotion-ball-pet'/)
  assert.match(hostSource, /plugins\?\.find\(\(candidate\) => candidate\.name === DESKTOP_PET_PLUGIN_NAME\)/)
  assert.doesNotMatch(hostSource, /plugins\?\.\[0\]/)
})

test('desktop plugin host prevents persistent browser zoom drift', () => {
  assert.match(hostSource, /event\.preventDefault\(\)/)
  assert.match(hostSource, /\['\+', '-', '=', '0'\]\.includes\(event\.key\)/)
  assert.match(hostSource, /\{ passive: false \}/)
})

test('desktop pet separates hit surfaces from window drag surfaces', () => {
  assert.match(petSource, /document\.elementsFromPoint\(x, y\)/)
  assert.match(petSource, /target\.closest\('\[data-pet-drag-surface\]'\)/)
  assert.match(petSource, /if \(!dragSurface\) return/)
  assert.doesNotMatch(petSource, /target\.closest\('button, textarea, input, select, a'\)/)
})

test('keeps the native window interactive during active pointer workflows', () => {
  assert.equal(logic.shouldPassCursorThrough({ hitSurface: true }), false)
  assert.equal(logic.shouldPassCursorThrough({ pointerInteractionActive: true }), false)
  assert.equal(logic.shouldPassCursorThrough({ fileDragActive: true }), false)
  assert.equal(logic.shouldPassCursorThrough({ windowDragActive: true }), false)
  assert.equal(logic.shouldPassCursorThrough({}), true)
})

test('serializes passthrough updates and refreshes them across window transitions', () => {
  assert.match(petSource, /if \(pointerPassthroughInFlight\) \{\s+pointerPassthroughRequested = true/)
  assert.match(petSource, /activePointerIds\.add\(event\.pointerId\)/)
  assert.match(petSource, /activePointerIds\.delete\(event\.pointerId\)/)
  assert.match(petSource, /function applyAnchor[\s\S]*?requestPointerPassthroughUpdate\(\)/)
  assert.match(petSource, /state\.expansionPending = false;\s+requestPointerPassthroughUpdate\(\)/)
})

test('calibrates cursor coordinates against the rendered plugin viewport', () => {
  assert.match(petSource, /viewportWidth: window\.innerWidth/)
  assert.match(petSource, /viewportHeight: window\.innerHeight/)
  assert.match(hostSource, /message\.command === 'get_desktop_plugin_cursor_position'/)
})

test('derives native window dimensions from the measured component surface', () => {
  assert.equal(JSON.stringify(logic.surfaceWindowSize({
    surfaceWidth: 360,
    surfaceHeight: 344,
    overlapRail: 130,
    edgeInset: 8,
    minimumWidth: 256,
    minimumHeight: 288,
  })), JSON.stringify({ width: 506, height: 360 }))
  assert.equal(JSON.stringify(logic.surfaceWindowSize({
    surfaceWidth: 180,
    surfaceHeight: 120,
    overlapRail: 40,
    edgeInset: 8,
    minimumWidth: 256,
    minimumHeight: 288,
  })), JSON.stringify({ width: 256, height: 288 }))
  assert.match(petSource, /function measureViewModeViewport\(mode\)/)
  assert.match(petSource, /measurement\.getBoundingClientRect\(\)/)
})

test('passes measured surface dimensions through both view-mode host commands', () => {
  assert.match(petSource, /contentWidth: targetViewport\.width/)
  assert.match(petSource, /contentHeight: targetViewport\.height/)
  assert.match(petSource, /viewportWidth: window\.innerWidth/)
  assert.match(petSource, /viewportHeight: window\.innerHeight/)
  assert.match(petSource, /appliedViewportSignature/)
  assert.match(hostSource, /message\.command === 'set_desktop_plugin_view_mode'[\s\S]*\.\.\.measuredViewportArgs\(\)/)
  assert.match(hostSource, /message\.command === 'get_desktop_plugin_view_mode_transition'[\s\S]*\.\.\.measuredViewportArgs\(\)/)
})
