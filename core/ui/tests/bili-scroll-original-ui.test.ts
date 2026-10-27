// user:“不需要 lamtools 重写 就移植原版就行”+(直接运行原版 React 界面，宿主适配不得重画组件)。
import { afterEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'
// @ts-expect-error the plugin ships as a built browser module
import { mount } from '../../../plugins/bili-scroll/ui/page.mjs'

const cleanups: (() => void)[] = []
afterEach(() => { cleanups.splice(0).forEach(dispose => dispose()); document.body.replaceChildren() })

it('renders upstream tabs, switches, card filters and pagination using existing host operations', async () => {
  const config = { perDay: 5, keywords: ['本地模型'], peakValley: false, dmMode: 'only' }
  const rpc = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    if (method.endsWith('.status')) return { ok: true, pickedToday: 0, env: { venvReady: true, loggedIn: true } }
    if (method.endsWith('.config_get')) return { config }
    if (method.endsWith('.config_update')) { Object.assign(config, params.patch); return { ok: true, config } }
    if (method.endsWith('.fav_folders')) return { ok: true, folders: [{ id: 42, title: '默认收藏夹', count: 1 }] }
    if (method.endsWith('.watched')) return { ok: true, items: [{ bvid: 'BV1234567890', title: '原版卡片', state: 'picked', day: '2026-10-26' }], total: 60 }
    if (method.endsWith('.install_log')) return { lines: [] }
    if (method.endsWith('.cover_data')) return { ok: true, data_url: 'data:image/png;base64,iVBORw0KGgo=' }
    return { ok: true }
  })
  const root = document.createElement('div'); document.body.append(root)
  cleanups.push(mount(root, { rpc, signal: new AbortController().signal, visible: true, onVisibilityChange: () => () => {} }))
  await vi.waitFor(() => expect(root.querySelector('[data-bd-tabs]')).not.toBeNull())
  expect([...root.querySelectorAll('[data-bd-tab]')].map(node => node.textContent)).toEqual(['日常', '偏好', '互动', '高级'])
  expect(root.querySelector('.bili-page')).toBeNull()
  const button = (text: string) => [...root.querySelectorAll('button')].find(node => node.textContent === text)!
  ;(root.querySelector('[data-bd-sw]') as HTMLButtonElement).click()
  await vi.waitFor(() => expect(rpc).toHaveBeenCalledWith('bili-scroll.config_update', { patch: { peakValley: true } }))
  button('看它刷过什么').click()
  await vi.waitFor(() => expect(root.querySelector('[data-bd-item]')).not.toBeNull())
  expect(root.textContent).toContain('原版卡片')
  button('下一页').click()
  await vi.waitFor(() => expect(rpc).toHaveBeenCalledWith('bili-scroll.watched', expect.objectContaining({ offset: 30, limit: 30 })))
})

it('retains the exact upstream client source alongside the adapter', () => {
  const source = readFileSync(resolve('../../plugins/bili-scroll/vendor/dsh-client.js'))
  expect(createHash('sha256').update(source).digest('hex')).toBe('f7cd091239399755c6efeb90f516bdf39e3268d58b022ec27f7d6285cc809350')
})
