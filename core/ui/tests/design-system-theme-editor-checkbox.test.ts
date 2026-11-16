import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { STUDIO_PREVIEW_STYLE_ID } from '../src/themeStudio/runtime'

const preview = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_PREVIEW_STYLE_ID}"]`)?.textContent || ''
afterEach(() => { localStorage.clear(); document.body.innerHTML = ''; document.querySelectorAll('style[data-ui-theme-studio]').forEach(node => node.remove()) })

describe('theme editor shared checkboxes', () => {
  it('preserves live visibility preview', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="visibility"].sunday-checkbox').setValue(false)
    await flushPromises()
    expect(preview()).toContain('display: none')
    wrapper.unmount()
  })
  it('preserves the image overflow setting', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({ schemaVersion: 1, themeId: 'studio', nodes: { 'shell.sidebar': { background: { type: 'asset', assetRef: 'asset-abc123', fit: 'cover', overflow: 'clipped' } } }, templates: {}, instances: {}, breakpoints: [], assets: [{ id: 'asset-abc123', sha256: 'a'.repeat(64), mime: 'image/png', width: 200, height: 100, url: 'data:image/png;base64,QQ==' }], updatedAt: new Date().toISOString() }))
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-asset-overflow].sunday-checkbox').setValue(true)
    await flushPromises()
    expect(preview()).toContain('overflow: visible')
    wrapper.unmount()
  })
})

