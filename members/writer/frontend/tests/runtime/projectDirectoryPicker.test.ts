import assert from 'node:assert/strict'
import test from 'node:test'
import { pickProjectDirectory, projectNameFromPath } from '../../src/lib/project-directory-picker.ts'

test('pickProjectDirectory uses the desktop directory selector when available', async () => {
  const result = await pickProjectDirectory({
    selectDirectory: async () => 'E:\\Work\\DemoProject',
  })

  assert.deepEqual(result, {
    path: 'E:\\Work\\DemoProject',
    source: 'desktop',
  })
})

test('pickProjectDirectory reports unsupported browser without fabricating a path', async () => {
  const result = await pickProjectDirectory(undefined)

  assert.equal(result.path, '')
  assert.equal(result.source, 'unsupported')
  assert.match(result.message ?? '', /绝对路径/)
})

test('pickProjectDirectory falls back to the app-server picker in browser mode', async () => {
  const result = await pickProjectDirectory({
    appServerPickDirectory: async () => 'E:\\BrowserPicked',
  })

  assert.deepEqual(result, {
    path: 'E:\\BrowserPicked',
    source: 'app-server',
  })
})

test('projectNameFromPath returns the last directory segment', () => {
  assert.equal(projectNameFromPath('E:\\Work\\DemoProject'), 'DemoProject')
  assert.equal(projectNameFromPath('/home/lam/demo'), 'demo')
})
