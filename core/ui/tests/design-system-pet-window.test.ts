import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import PetSettingsPanel from '../src/pet/ui/PetSettingsPanel.vue'
import { defaultConfig } from '../src/pet/config'

vi.mock('../src/pet/bridge.ts', () => ({ setZMode: vi.fn(async () => {}), notifyOverlaySettingsChanged: vi.fn(async () => {}) }))

describe('pet window shared controls', () => {
  it('preserves live L3 and Ping settings while using shared checkboxes', async () => {
    const runtime = {
      config: reactive(defaultConfig()), petRecords: { value: [] }, configWarnings: { value: [] }, errors: { value: [] }, agents: { value: null },
      stats: { fps: 0, tickMs: 0, drawMs: 0 }, worldStats: { value: { terrainSegments: 0, tileSolid: 0, tilePlatform: 0, tileLadder: 0 } },
      setUseL3: vi.fn(), schedulePingSave: vi.fn(), scheduleSave: vi.fn(), debug: {},
    }
    const wrapper = mount(PetSettingsPanel, { props: { runtime: runtime as any } })
    const rows = wrapper.findAll('label.settings__row')
    const l3 = rows.find(row => row.text().includes('L3 视觉边缘识别'))!.get('input.sunday-checkbox')
    const screenshot = rows.find(row => row.text().includes('自动附当前截图'))!.get('input.sunday-checkbox')
    await l3.setValue(true)
    expect(runtime.setUseL3).toHaveBeenCalledWith(true)
    await screenshot.setValue(!runtime.config.ping.autoAttachScreenshot)
    expect(runtime.schedulePingSave).toHaveBeenCalled()
    expect(wrapper.findAll('.settings__sector input.sunday-checkbox')).toHaveLength(runtime.config.ping.sectors.length)
    wrapper.unmount()
  })
  it('uses shared menus for geometry, quality, font and bubble settings', async () => {
    const runtime = {
      config: reactive(defaultConfig()), petRecords: { value: [] }, configWarnings: { value: [] }, errors: { value: [] }, agents: { value: null },
      stats: { fps: 0, tickMs: 0, drawMs: 0 }, worldStats: { value: { terrainSegments: 0, tileSolid: 0, tilePlatform: 0, tileLadder: 0 } },
      setQuality: vi.fn(), schedulePingSave: vi.fn(), scheduleSave: vi.fn(), debug: {},
    }
    const wrapper = mount(PetSettingsPanel, { props: { runtime: runtime as any }, global: { stubs: { Teleport: true } } })
    for (const [label, text] of [['真实遮挡模式', '置顶 + 按窗口几何裁剪（推荐）'], ['几何精度', '高（更贴边缘）'], ['弹幕字体', '楷体'], ['Agent 提问', '静默']]) {
      const row = wrapper.findAll('label.settings__row').find(item => item.text().includes(label))!
      await row.get('.ui-select-trigger').trigger('click')
      await row.findAll('.ui-select-option').find(item => item.text() === text)!.trigger('click')
    }
    expect(runtime.config.zMode).toBe('clip')
    expect(runtime.setQuality).toHaveBeenCalledWith('high')
    expect(runtime.config.overlay.danmaku.fontFamily).toBe('KaiTi, STKaiti, serif')
    expect(runtime.config.bubbles.question).toBe('silent')
    expect(runtime.scheduleSave).toHaveBeenCalled()
    wrapper.unmount()
  })

})
