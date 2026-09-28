import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CorePluginsEditor from '../src/components/CorePluginsEditor.vue'
import { createFakeTransport } from './fake-transport'

const transport = createFakeTransport()

const PLUGIN = {
  name: 'lamtools-rag',
  version: '0.1.0',
  description: 'RAG',
  root: 'E:\\plugins\\lamtools-rag',
  enabled: true,
  skills: [],
  hooks: [],
  mcp: [],
  tools: [],
  skill_names: [],
  hook_summary: [],
  dependencies: [],
  deps_status: 'none',
  config_schema: 'E:\\plugins\\lamtools-rag\\config\\schema.jsonc',
}

const SCHEMA = {
  type: 'object',
  properties: {
    autoRoots: { type: 'array', items: { type: 'string' } },
  },
}

function makeRpc() {
  return vi.fn(async (method: string) => {
    switch (method) {
      case 'plugin.list':
        return { plugins: [PLUGIN], errors: [] }
      case 'plugin.config.get':
        return { name: 'lamtools-rag', config: { autoRoots: [] }, schema: SCHEMA, work_root: 'E:\\ws' }
      default:
        return {}
    }
  })
}

/**
 * The config card owns a folder-browser dialog that teleports into a host inside
 * the card. The card could not be closed at all: the dialog mounts before its
 * host is in the document, Vue leaves a subtree it could not teleport behind,
 * and unmounting that subtree throws — leaving the card on screen with no way
 * out (reported on mobile, where there is no other exit).
 */
describe('plugin config card dismissal', () => {
  it('closes from the close button without a runtime error', async () => {
    const warnings: string[] = []
    const warn = vi.spyOn(console, 'warn').mockImplementation((...args: unknown[]) => {
      warnings.push(args.map(String).join(' '))
    })
    try {
      const wrapper = mount(CorePluginsEditor, {
        attachTo: document.body,
        props: { requestRpc: makeRpc(), transport },
      })
      await flushPromises()

      // The dialog's teleport target has to resolve; an unresolved selector is
      // what left the broken subtree behind.
      expect(warnings.filter((line) => line.includes('Teleport target'))).toEqual([])

      const configBtn = wrapper.find('button[aria-label="配置"]')
      expect(configBtn.exists()).toBe(true)
      await configBtn.trigger('click')
      await flushPromises()
      expect(document.querySelector('.plugin-config-popover')).not.toBeNull()
      // The dialog renders into the card's host, not into the document body.
      expect(document.querySelector('.plugin-folder-host > *')).not.toBeNull()

      await wrapper.find('.editor-popover-close').trigger('click')
      await flushPromises()

      expect(document.querySelector('.plugin-config-popover')).toBeNull()
      wrapper.unmount()
    } finally {
      warn.mockRestore()
    }
  })

  it('closes when the backdrop is tapped, not only from the close button', async () => {
    const wrapper = mount(CorePluginsEditor, {
      attachTo: document.body,
      props: { requestRpc: makeRpc(), transport },
    })
    await flushPromises()
    await wrapper.find('button[aria-label="配置"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('.plugin-config-popover')).not.toBeNull()

    const overlay = document.querySelector('.editor-overlay') as HTMLElement
    const card = document.querySelector('.plugin-config-popover') as HTMLElement
    // Press and release on backdrop space (outside the card, inside the overlay).
    const outside = overlay.getBoundingClientRect()
    const point = { clientX: outside.left + 4, clientY: outside.top + 4 }
    overlay.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, isPrimary: true, ...point }))
    document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1, isPrimary: true, ...point }))
    await flushPromises()

    expect(card.contains(document.querySelector('.plugin-config-popover'))).toBe(false)
    expect(document.querySelector('.plugin-config-popover')).toBeNull()
    wrapper.unmount()
  })
})
