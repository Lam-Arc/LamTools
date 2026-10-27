// user:“不需要 lamtools 重写 就移植原版就行”+(配置与生命周期继续验收原版组件，不能依赖已废弃的自绘选择器)。
import { expect, it, vi } from 'vitest'
// @ts-expect-error the plugin is a built JavaScript module
import { mount } from '../../../plugins/bili-scroll/ui/page.mjs'

it('saves the original persona form and cleans up its React tree and styles', async () => {
  const config = { perDay: 5, personaPrompt: '', keywords: [] }
  const rpc = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    if (method.endsWith('config_get')) return { config }
    if (method.endsWith('status')) return { ok: true, env: {}, pickedToday: 1 }
    if (method.endsWith('install_log')) return { lines: [] }
    if (method.endsWith('fav_folders')) return { ok: true, folders: [] }
    return { ok: true, config: { ...config, ...((params.patch || {}) as object) } }
  })
  const root = document.createElement('div'); document.body.append(root)
  const controller = new AbortController()
  const cleanup = mount(root, { rpc, signal: controller.signal, visible: true, onVisibilityChange: () => () => {} })
  try {
    await vi.waitFor(() => expect(root.querySelector('[data-bd-tabs]')).not.toBeNull())
    const taste = [...root.querySelectorAll<HTMLButtonElement>('[data-bd-tab]')].find(button => button.textContent === '偏好')!
    taste.click()
    await vi.waitFor(() => expect(taste.getAttribute('aria-selected')).toBe('true'))
    const persona = root.querySelectorAll<HTMLTextAreaElement>('[data-bd-group="taste"] textarea')[1]
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(persona, '说得简洁些')
    persona.dispatchEvent(new Event('input', { bubbles: true }))
    await new Promise(resolve => setTimeout(resolve, 0))
    ;[...root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '保存')!.click()
    await vi.waitFor(() => expect(rpc).toHaveBeenCalledWith('bili-scroll.config_update', { patch: { keywords: [], personaPrompt: '说得简洁些' } }))
  } finally { controller.abort(); cleanup(); root.remove() }
  expect(root.childElementCount).toBe(0)
  expect(document.querySelector('[data-plugin-css="dsh-bili-scroll"]')).toBeNull()
})
