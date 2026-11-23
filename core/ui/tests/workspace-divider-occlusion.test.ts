// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h, inject, onMounted, ref } from 'vue'
import { expect, it } from 'vitest'
import CoreWorkspace from '@/components/CoreWorkspace.vue'
import { buildCutoutClipPath } from '@/workspace/composition'
import { WORKSPACE_COMPOSED_RECT } from '@/components/workspaceInjection'
import { useWorkspace, type WorkspaceController } from '@/workspace/useWorkspace'

it('clips a divider only where a native webpage floats across it', async () => {
  const workspace = useWorkspace(ref('divider-occlusion'), undefined, undefined, { persist: false })
  workspace.setBounds({ x: 0, y: 0, width: 1000, height: 700 })
  workspace.split('main', 'right')
  const browser = workspace.add('browser', 'https://example.test', 'Web', 'main')!
  workspace.setSurfaceMode(browser.id, 'float')
  let publish: ((rect: { x: number; y: number; width: number; height: number } | null) => void) | undefined
  const Web = defineComponent({
    setup() {
      const report = inject(WORKSPACE_COMPOSED_RECT)!
      onMounted(() => { publish = rect => report(browser.id, rect) })
      return () => h('div')
    },
  })
  const wrapper = mount(CoreWorkspace, {
    props: { controller: workspace, workRoot: '' },
    slots: { default: ({ tab }: { tab: WorkspaceController['tabs']['value'][number]['tab'] }) => tab.id === browser.id ? h(Web) : null },
  })
  try {
    const divider = wrapper.get<HTMLElement>('[data-ws2-divider]').element
    const x = parseFloat(divider.style.left)
    publish!({ x: x - 30, y: 125, width: 250, height: 240 })
    await wrapper.vm.$nextTick()
    expect(divider.style.clipPath).toContain('polygon(evenodd')
    expect(divider.style.clipPath).toContain('125px')
    expect(divider.style.clipPath).toContain('365px')
    publish!({ x: x + 40, y: 125, width: 250, height: 240 })
    await wrapper.vm.$nextTick()
    expect(divider.style.clipPath).toBe('')
    publish!(null)
    await wrapper.vm.$nextTick()
    expect(divider.style.clipPath).toBe('')
  } finally { wrapper.unmount() }
})

it('keeps fractional native edges when drawing the floating webpage cutout', () => {
  const path = buildCutoutClipPath({ x: 100, y: 0 }, [{ x: 104.8, y: 115.2, width: 40, height: 64 }])
  expect(path).toContain('115.2px')
  expect(path).toContain('179.2px')
})
