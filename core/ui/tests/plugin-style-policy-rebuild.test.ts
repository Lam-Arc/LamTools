// user:“插件窗口的所有东西都被渲染成了文本，它自己的样式好像全部都丢了”+(插件样式继承打包页 nonce，挂载失败和关闭都清理)。
import { afterEach, expect, it, vi } from 'vitest'
import { createPluginPageInstance } from '../src/plugins/pages'

afterEach(() => document.querySelectorAll('[data-plugin-style], #nonce-anchor').forEach(node => node.remove()))

it('gives plugins a document-local style API using the actual nonce and cleans it up', async () => {
  const anchor = document.createElement('style'); anchor.id = 'nonce-anchor'; anchor.nonce = 'packaged-page-nonce'
  document.head.append(anchor)
  const host = document.createElement('div')
  const instance = createPluginPageInstance(host, { plugin: 'probe', id: 'main', title: 'Probe', entry_url: '/probe.mjs' },
    { instanceId: 'probe:main', workRoot: '' }, vi.fn(), { loadModule: async () => ({
      mount(root, context) { context.addStyle('.probe { display: grid }'); root.className = 'probe' },
    }) })
  await instance.ready
  const style = document.head.querySelector<HTMLStyleElement>('[data-plugin-style]')!
  expect(style.nonce).toBe('packaged-page-nonce')
  expect(style.textContent).toContain('display: grid')
  await instance.dispose()
  expect(document.head.querySelector('[data-plugin-style]')).toBeNull()
})

it('cleans up styles created by a plugin that fails during mount', async () => {
  const instance = createPluginPageInstance(document.createElement('div'), { plugin: 'probe', id: 'main', title: 'Probe', entry_url: '/probe.mjs' },
    { instanceId: 'probe:failed', workRoot: '' }, vi.fn(), { loadModule: async () => ({
      mount(_, context) { context.addStyle('.probe { display: flex }'); throw new Error('mount failed') },
    }) })
  await expect(instance.ready).rejects.toThrow('mount failed')
  expect(document.head.querySelector('[data-plugin-style]')).toBeNull()
})
