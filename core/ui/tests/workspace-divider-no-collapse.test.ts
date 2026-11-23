// @vitest-environment jsdom
/**
 * user:“分屏有问题，我随便拖动了一下导致分屏完全消失，无法出现了”
 * user:“无法拖动，它位置只会大幅跳变”
 * user:“更好的方式是折叠就等于关闭，这样可以通过右上角标签页抽屉直接再次将其显示出来”
 * (验收四条：① 拖分隔条只缩放，永不收起/关闭分屏；② 分隔条只跟指针位移走，不被左侧栏/标题栏的偏移顶到极端；
 *  ③ 收起一块分屏 = 关掉它并把标签放进「已收起」，抽屉里点一下就能唤回，内容不销毁；
 *  ④ 存档里不再有折叠态，旧存档里的 collapsed 直接忽略)。
 */
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { expect, it } from 'vitest'
import CoreWorkspace, { DIVIDER_MIN_PANE_PX, clampDividerRatio } from '@/components/CoreWorkspace.vue'
import CoreWorkspaceTabDrawer from '@/components/CoreWorkspaceTabDrawer.vue'
import { useWorkspace } from '@/workspace/useWorkspace'
import {
  areasOf,
  createWorkspace,
  parseWorkspace,
  serializeWorkspace,
  type SurfaceRef,
} from '@/workspace'

const refs: SurfaceRef[] = [
  { id: 'agent', kind: 'agent', title: 'Agent' },
  { id: 'web', kind: 'browser', title: '浏览器' },
]

function make(key: string) {
  const controller = useWorkspace(ref(key), undefined, undefined, { persist: false })
  controller.setBounds({ x: 0, y: 0, width: 1200, height: 800 })
  return controller
}

const frame = () => new Promise<void>(resolve => { requestAnimationFrame(() => resolve()) })

it('分隔条比例被夹在“两侧都留得住”的范围内，永远到不了 0 或 1', () => {
  const extent = 1200
  expect(clampDividerRatio(0, extent)).toBeCloseTo(DIVIDER_MIN_PANE_PX / extent, 5)
  expect(clampDividerRatio(1, extent)).toBeCloseTo(1 - DIVIDER_MIN_PANE_PX / extent, 5)
  expect(clampDividerRatio(.5, extent)).toBe(.5)
  // 联合区很窄时最小值封顶 40%，不会把两侧一起挤没。
  expect(clampDividerRatio(0, 200)).toBe(.4)
  expect(clampDividerRatio(1, 200)).toBe(.6)
  // 还没测量出尺寸时原样返回，绝不返回 NaN。
  expect(clampDividerRatio(.3, 0)).toBe(.3)
  expect(clampDividerRatio(Number.NaN, extent)).toBe(.5)
})

it('把分隔条拖到边缘只会缩放，不会收起或移除分屏', () => {
  const controller = make('divider-edge')
  const aux = controller.split('main', 'right')!
  const tab = controller.add('browser', 'https://example.test', '网页', aux)!
  expect(tab).toBeTruthy()
  for (const raw of [0, .001, .03, .5, .97, .999, 1]) {
    controller.resizeDivider([], clampDividerRatio(raw, 1200))
    const geometry = controller.geometry.value
    expect(geometry.areas[aux]).toBeTruthy()
    expect(geometry.areas.main).toBeTruthy()
    expect(geometry.areas[aux].rect.width).toBeGreaterThan(0)
    expect(geometry.areas.main.rect.width).toBeGreaterThan(0)
  }
  expect(areasOf(controller.model.value).map(area => area.id).sort()).toEqual([aux, 'main'].sort())
  expect(controller.parkedFloats.value).toEqual([])
})

it('真实指针事件：把分隔条甩出屏幕两端，分屏都还在', async () => {
  const controller = make('divider-pointer')
  const aux = controller.split('main', 'right')!
  const wrapper = mount(CoreWorkspace, { props: { controller, workRoot: '' } })
  try {
    await nextTick()
    const divider = wrapper.get('[data-ws2-divider]').element as HTMLElement
    // jsdom 的 MouseEvent.button 只读，所以直接派发原生事件，不用 trigger 的改写参数。
    const fire = (type: string, x: number) => {
      divider.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: 300, button: 0 }))
    }
    fire('pointerdown', 600)
    fire('pointermove', 5000)
    await frame()
    expect(areasOf(controller.model.value).map(area => area.id).sort()).toEqual([aux, 'main'].sort())
    expect(controller.geometry.value.areas[aux]).toBeTruthy()
    fire('pointermove', -3000)
    await frame()
    expect(areasOf(controller.model.value).map(area => area.id).sort()).toEqual([aux, 'main'].sort())
    expect(controller.geometry.value.areas[aux]).toBeTruthy()
    fire('pointerup', 600)
    expect(controller.parkedFloats.value).toEqual([])
  } finally {
    wrapper.unmount()
  }
})

it('分隔条只跟指针位移走：窗口有左侧栏/标题栏偏移时也不会跳', async () => {
  const controller = make('divider-offset')
  const aux = controller.split('main', 'right')!
  const wrapper = mount(CoreWorkspace, { props: { controller, workRoot: '' } })
  // 真实窗口里工作区原点不在视口原点：左侧栏 300px + 标题栏 36px。
  const originX = 300
  const originY = 36
  try {
    await nextTick()
    const divider = wrapper.get('[data-ws2-divider]').element as HTMLElement
    const boundary = controller.geometry.value.areas[aux].rect.x
    const fire = (type: string, x: number) => {
      divider.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x + originX, clientY: 300 + originY, button: 0 }))
    }
    fire('pointerdown', boundary)
    // 往右拖 120px：比例只该涨 120/1200，而不是被 300px 偏移顶到 0.85。
    fire('pointermove', boundary + 120)
    await frame()
    const tree = controller.model.value.tree
    expect(tree.kind === 'split' ? tree.ratio : 0).toBeCloseTo(.5 + 120 / 1200, 2)
    // 再拖回起点：回到 0.5，而不是被夹到最左。
    fire('pointermove', boundary)
    await frame()
    const back = controller.model.value.tree
    expect(back.kind === 'split' ? back.ratio : 0).toBeCloseTo(.5, 2)
    fire('pointerup', boundary)
  } finally {
    wrapper.unmount()
  }
})

it('收起分屏 = 关闭：标签进「已收起」，抽屉里点一下就能唤回', async () => {
  const controller = make('divider-park')
  const aux = controller.split('main', 'right')!
  const tab = controller.add('browser', 'https://example.test', '网页', aux)!
  controller.collapseArea(aux)
  // 区域收拢了，内容还在。
  expect(controller.areas.value.map(entry => entry.area.id)).toEqual(['main'])
  expect(controller.parkedFloats.value.map(item => item.id)).toContain(tab.id)

  const drawer = mount(CoreWorkspaceTabDrawer, { props: { controller } })
  try {
    await drawer.get('[data-ws2-tab-drawer-trigger]').trigger('click')
    const row = drawer.get(`[data-ws2-drawer-item="${tab.id}"]`)
    expect(row.text()).toContain('已收起')
    await row.get('.ws2-tab-drawer__main').trigger('click')
    // 抽屉里点一下 → 内容回到可见的浮层，不再留在「已收起」。
    expect(controller.floats.value.map(entry => entry.tab.id)).toContain(tab.id)
    expect(controller.parkedFloats.value.map(item => item.id)).not.toContain(tab.id)
  } finally {
    drawer.unmount()
  }
})

it('关掉分屏（面板关闭键）也不销毁内容：标签进「已收起」', () => {
  const controller = make('divider-close-pane')
  const aux = controller.split('main', 'right')!
  const tab = controller.add('browser', 'https://example.test', '网页', aux)!
  controller.closePane(aux)
  expect(controller.areas.value.map(entry => entry.area.id)).toEqual(['main'])
  expect(controller.parkedFloats.value.map(item => item.id)).toContain(tab.id)
})

it('存档里不再有折叠态，旧存档里的 collapsed 被忽略', () => {
  const base = createWorkspace(refs, 'agent')
  const model = {
    ...base,
    tree: {
      kind: 'split' as const,
      direction: 'row' as const,
      ratio: .5,
      a: { kind: 'leaf' as const, area: { id: 'main', tabs: ['agent'], active: 'agent', role: 'main' as const, axis: 'vertical' as const } },
      b: { kind: 'leaf' as const, area: { id: 'aux', tabs: ['web'], active: 'web', role: 'aux' as const, axis: 'horizontal' as const } },
    },
  }
  const payload = JSON.parse(serializeWorkspace(model))
  expect('collapsed' in payload).toBe(false)

  const legacy = parseWorkspace(JSON.stringify({ ...payload, collapsed: { aux: 'end' } }), base)
  expect(areasOf(legacy.model).map(area => area.id).sort()).toEqual(['aux', 'main'])
  expect(legacy.model.tree.kind).toBe('split')
})
