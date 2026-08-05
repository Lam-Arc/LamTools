import assert from 'node:assert/strict'
import test from 'node:test'
import { isPassiveReplaySessionStatus, isTerminalSessionStatus } from '../../src/runtime/sessionStatus.ts'

test('terminal session status excludes waiting and idle', () => {
  assert.equal(isTerminalSessionStatus('completed'), true)
  assert.equal(isTerminalSessionStatus('failed'), true)
  assert.equal(isTerminalSessionStatus('cancelled'), false)
  assert.equal(isTerminalSessionStatus('waiting'), false)
  assert.equal(isTerminalSessionStatus('running'), false)
  assert.equal(isTerminalSessionStatus('idle'), false)
  assert.equal(isTerminalSessionStatus('active'), false)
  assert.equal(isTerminalSessionStatus(''), false)
})

test('passive replay status includes idle and waiting without calling them terminal', () => {
  assert.equal(isPassiveReplaySessionStatus('idle'), true)
  assert.equal(isPassiveReplaySessionStatus('waiting'), true)
  assert.equal(isPassiveReplaySessionStatus('completed'), true)
  assert.equal(isPassiveReplaySessionStatus('failed'), true)
  assert.equal(isPassiveReplaySessionStatus('running'), false)
})
