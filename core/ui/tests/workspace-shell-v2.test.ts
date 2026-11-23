import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { createRectQueue, keyboardIntent, useWorkspace } from '../src/workspace/useWorkspace'
import { areasOf, computeWorkspace, DEFAULT_GAP, DEFAULT_LIMITS } from '../src/workspace'
import { TAB_DRAG_THRESHOLD, createTabDragMachine, planTabDrop } from '../src/components/CoreWorkspace.vue'

/**
 * user:“验收（自证）：至少覆盖单区铺满、两区完整分割、T 形、分隔条拖动、拖标签跨区、
 * pin/unpin、浮层拖动每帧一次、insufficient 不隐藏区域、键盘映射”+
 * (这些都是纯行为，不需要挂载 Vue 组件：控制器把引擎结论翻出来，测试直接查数字)。
 */
function make(width = 1000, height = 600) {
  const controller = useWorkspace(ref('test.workspace.v4'), ref('/root'), ref(null), { persist: false })
  controller.setBounds({ x: 0, y: 0, width, height })
  return controller
}

describe('区域渲染：铺满、完整分割、T 形', () => {
  it('单区铺满整块工作区', () => {
    const controller = make()
    const areas = Object.values(controller.geometry.value.areas)
    expect(areas).toHaveLength(1)
    expect(areas[0].rect).toEqual({ x: 0, y: 0, width: 1000, height: 600 })
  })

  it('两区必须是完整左右分割：相加加间隙等于全宽，且互不重叠', () => {
    const controller = make()
    const created = controller.split('main', 'right')
    expect(created).toBeTruthy()
    const view = controller.geometry.value.areas
    const ids = Object.keys(view)
    expect(ids).toHaveLength(2)
    const [a, b] = ids.map(id => view[id].rect).sort((left, right) => left.x - right.x)
    expect(a.y).toBe(0)
    expect(b.y).toBe(0)
    expect(a.height).toBe(600)
    expect(b.height).toBe(600)
    // 完整左右：两块宽度 + 中间那条间隙正好铺满，没有第三块“角落小面板”。
    expect(a.width + DEFAULT_GAP + b.width).toBe(1000)
    expect(a.x + a.width).toBeLessThanOrEqual(b.x)
  })

  it('≥3 区允许 T 形：切出来的两块各自仍在一块矩形里', () => {
    const controller = make()
    const first = controller.split('main', 'right')
    expect(first).toBeTruthy()
    const second = controller.split(first!, 'bottom')
    expect(second).toBeTruthy()
    const view = controller.geometry.value.areas
    expect(Object.keys(view)).toHaveLength(3)
    for (const entry of Object.values(view)) {
      expect(entry.rect.width).toBeGreaterThan(0)
      expect(entry.rect.height).toBeGreaterThan(0)
    }
  })
})

describe('分隔条：拖动改 ratio，几何跟着变', () => {
  it('把比例拖到 30% 时会被主区下限挡住（引擎不压破最小尺寸）', () => {
    const controller = make()
    controller.split('main', 'right')
    controller.resizeDivider([], .3)
    const view = controller.geometry.value.areas
    const mainId = controller.areas.value.find(entry => entry.area.role === 'main')!.area.id
    // user:“最小尺寸永不靠藏屏满足”+(1000 可分配，30% 只有 300 < 主区下限 420，
    //  引擎把比例夹到 420/1000 而不是把主区压破——这正是旧版“压破最小尺寸”的解药)。
    expect(view[mainId].rect.width).toBe(DEFAULT_LIMITS.main.width)
  })

  it('在合法区间内拖动时，比例就是最终宽度', () => {
    const controller = make()
    controller.split('main', 'right')
    // 50/50 两侧都高于下限（主区 420、辅助 320），引擎不需要夹取。
    controller.resizeDivider([], .5)
    const view = controller.geometry.value.areas
    const mainId = controller.areas.value.find(entry => entry.area.role === 'main')!.area.id
    expect(view[mainId].rect.width).toBe(Math.round(1000 * .5))
  })

  it('两个方向都不会被拖到下限以下（下限优先于指针）', () => {
    const controller = make()
    controller.split('main', 'right')
    const mainId = controller.areas.value.find(entry => entry.area.role === 'main')!.area.id
    const auxId = controller.areas.value.find(entry => entry.area.role === 'aux')!.area.id
    const colours = () => ({
      main: controller.geometry.value.areas[mainId].rect.width,
      aux: controller.geometry.value.areas[auxId].rect.width,
    })
    // 往左拖到 30%：主区被夹在 420，辅助区拿走剩下的 580。
    controller.resizeDivider([], .3)
    expect(colours()).toEqual({ main: DEFAULT_LIMITS.main.width, aux: 1000 - DEFAULT_LIMITS.main.width })
    // 往右拖到 70%：辅助区被夹在 320，主区拿走剩下的 678。
    controller.resizeDivider([], .7)
    expect(colours()).toEqual({ main: 1000 - DEFAULT_LIMITS.aux.width, aux: DEFAULT_LIMITS.aux.width })
  })

  // user:“更好的方式是折叠就等于关闭，这样可以通过右上角标签页抽屉直接再次将其显示出来”+
  // (收起分屏 = 关掉这块分屏 + 标签进「已收起」：另一侧接管整块矩形，内容留在抽屉里可唤回)。
  it('收起分屏 = 关闭：另一侧接管整块矩形，标签进「已收起」并能唤回', () => {
    const controller = make()
    const created = controller.split('main', 'right')!
    const mainId = controller.areas.value.find(entry => entry.area.role === 'main')!.area.id
    const tab = controller.add('browser', 'https://example.test', '网页', created)!
    controller.collapseArea(created)
    const view = controller.geometry.value.areas
    expect(view[created]).toBeUndefined()
    expect(view[mainId].rect.width).toBe(1000)
    expect(controller.parkedFloats.value.map(item => item.id)).toContain(tab.id)
    controller.reviveFloat(tab.id)
    expect(controller.floats.value.map(entry => entry.tab.id)).toContain(tab.id)
  })
})

describe('拖标签：跨区移动', () => {
  it('把主区的标签拖进新区域后，仍只有一份实例（不复制）', () => {
    const controller = make()
    const browser = controller.add('browser', 'https://example.com', 'Example')
    expect(browser).toBeTruthy()
    const target = controller.split('main', 'right')
    expect(target).toBeTruthy()
    const mainArea = controller.state.panes.main
    const index = mainArea.tabs.findIndex(tab => tab.id === browser!.id)
    expect(index).toBeGreaterThanOrEqual(0)
    controller.moveTab({ pane: 'main', index }, { pane: target!, index: 0 })
    const moved = controller.state.panes[target!]
    expect(moved.tabs.map(tab => tab.id)).toContain(browser!.id)
    // user:“内容实例与布局分离：同一 tab 对象在移动间不复制（不要 {...tab}）”+
    // (state 是 reactive，读出来的是代理；所以用“改一个字段，两边都看得见”来证明是同一个底层对象，
    //  而不是拿代理和原对象比引用)。
    const movedTab = moved.tabs.find(tab => tab.id === browser!.id)!
    movedTab.title = '改过的标题'
    expect(browser!.title).toBe('改过的标题')
    expect(controller.state.panes.main.tabs.map(tab => tab.id)).not.toContain(browser!.id)
  })
})

describe('固定 / 解除固定', () => {
  it('浮层 pin 成区域给出落地矩形；unpin 又回到浮层', () => {
    const controller = make()
    const browser = controller.add('browser', 'https://example.com', 'Example')
    expect(browser).toBeTruthy()
    const asFloat = controller.setSurfaceMode(browser!.id, 'float')
    expect(asFloat.ok).toBe(true)
    expect(controller.floats.value.map(entry => entry.tab.id)).toContain(browser!.id)

    const plan = controller.pinPlan(browser!.id)
    expect(plan.ok).toBe(true)
    expect(plan.rect!.width).toBeGreaterThan(0)

    const committed = controller.pinCommit(browser!.id)
    expect(committed.ok).toBe(true)
    expect(controller.floats.value.map(entry => entry.tab.id)).not.toContain(browser!.id)
    const placement = controller.placementOf(browser!.id)
    expect(placement?.kind).toBe('area')

    const areaId = (placement as { kind: 'area'; areaId: string }).areaId
    const unpinned = controller.unpinCommit(areaId)
    expect(unpinned.ok).toBe(true)
    expect(controller.floats.value.map(entry => entry.tab.id)).toContain(browser!.id)
  })
})

describe('浮层跟手：每帧一次、值不变不写、松手补最后一帧', () => {
  it('同一帧内多次拖动只下发一次', () => {
    const queue = createRectQueue(() => {})
    const frames: Array<() => void> = []
    let writes = 0
    const q = createRectQueue(() => { writes += 1 }, { raf: (callback) => { frames.push(callback); return frames.length }, cancelRaf: () => { frames.length = 0 } })
    void queue
    for (let i = 0; i < 6; i += 1) q.schedule({ x: i * 10, y: 0, width: 400, height: 300 })
    expect(writes).toBe(0)
    expect(frames).toHaveLength(1)
    frames.splice(0).forEach(callback => callback())
    expect(writes).toBe(1)
  })

  it('矩形没变就不写；松手补最后一帧', () => {
    const frames: Array<() => void> = []
    const writes: number[] = []
    const q = createRectQueue(rect => writes.push(rect.x), {
      raf: (callback) => { frames.push(callback); return frames.length },
      cancelRaf: () => { frames.length = 0 },
      initial: { x: 0, y: 0, width: 400, height: 300 },
    })
    q.schedule({ x: 0, y: 0, width: 400, height: 300 })
    expect(q.pending).toBeNull()
    q.schedule({ x: 40, y: 0, width: 400, height: 300 })
    q.schedule({ x: 80, y: 0, width: 400, height: 300 })
    // 还没到帧：一次都没写。
    expect(writes).toEqual([])
    q.flush()
    // 松手补的是最后一次挂起的值（80），不是第一帧的 40。
    expect(writes).toEqual([80])
    frames.splice(0).forEach(callback => callback())
    expect(writes).toEqual([80])
  })

  it('浮层拖动属于 floating 相位，不让网页让位', () => {
    const controller = make()
    controller.beginInteraction('floating')
    expect(controller.interactionPhase.value).toBe('floating')
    controller.endInteraction()
    expect(controller.interactionPhase.value).toBe('idle')
  })
})

describe('空间不足：不隐藏区域，只给实数字据', () => {
  it('窗口比下限还窄时仍然画出区域，并把 need/have 摆出来', () => {
    const controller = make(300, 240)
    controller.split('main', 'right')
    const view = controller.geometry.value.areas
    // 关键：区域不会被“藏起来凑合”。
    expect(Object.keys(view)).toHaveLength(2)
    expect(controller.cramped.value).toBe(true)
    const info = controller.insufficient.value
    expect(info).not.toBeNull()
    expect(info!.need).toBeGreaterThan(0)
    expect(info!.have).toBeGreaterThanOrEqual(0)
    expect(controller.foldDetails.value?.needed).toBe(info!.need)
  })

  it('窗口足够大时没有 insufficient', () => {
    const controller = make()
    expect(controller.cramped.value).toBe(false)
    expect(controller.insufficient.value).toBeNull()
  })
})

describe('键盘映射', () => {
  it('Ctrl+\\ 向右分屏，Ctrl+Shift+\\ 向下分屏', () => {
    expect(keyboardIntent({ key: '\\', ctrlKey: true })).toEqual({ kind: 'split', edge: 'right' })
    expect(keyboardIntent({ key: '\\', ctrlKey: true, shiftKey: true })).toEqual({ kind: 'split', edge: 'bottom' })
  })

  it('Ctrl+W 只关辅助区、Alt+1..9 切屏、Ctrl+Tab 切标签、Ctrl+Shift+Enter 聚焦、Esc 退出', () => {
    expect(keyboardIntent({ key: 'w', ctrlKey: true })).toEqual({ kind: 'close-aux' })
    expect(keyboardIntent({ key: '3', altKey: true })).toEqual({ kind: 'select-area', index: 2 })
    expect(keyboardIntent({ key: 'Tab', ctrlKey: true })).toEqual({ kind: 'cycle-tab', reverse: false })
    expect(keyboardIntent({ key: 'Tab', ctrlKey: true, shiftKey: true })).toEqual({ kind: 'cycle-tab', reverse: true })
    expect(keyboardIntent({ key: 'Enter', ctrlKey: true, shiftKey: true })).toBeNull()
    expect(keyboardIntent({ key: 'Escape' })).toEqual({ kind: 'escape' })
    expect(keyboardIntent({ key: 'a' })).toBeNull()
  })
})

describe('几何下限：与引擎口径一致', () => {
  it('引擎给的两区最小宽等于主区 + 辅助区 + 间隙', () => {
    const controller = make()
    controller.split('main', 'right')
    const minimum = DEFAULT_LIMITS.main.width + DEFAULT_GAP + DEFAULT_LIMITS.aux.width
    const pure = computeWorkspace(controller.model.value, { x: 0, y: 0, width: minimum, height: 600 })
    expect(pure.issues.filter(issue => issue.code === 'insufficient')).toHaveLength(0)
    const narrow = computeWorkspace(controller.model.value, { x: 0, y: 0, width: minimum - 1, height: 600 })
    expect(narrow.issues.some(issue => issue.code === 'insufficient')).toBe(true)
  })
})

// user:“V2-C1b-4：拖标签落点判定只用 workspace/hit.ts；三种结果=同区排序 / 跨区移动 / 拖到区域边缘=切分”+
// (五条用例逐条对应验收；落点全部由 hitWorkspace + dropEdgeFor 给出，测试里不自己算几何)。
describe('标签拖拽：引擎落点', () => {
  function setup() {
    const controller = make()   // 1000 × 600
    const browser = controller.add('browser', 'https://example.com', 'B')!
    const model = controller.model.value
    const geometry = controller.geometry.value
    const main = areasOf(model).find(area => area.id === 'main')!
    const index = main.tabs.indexOf(browser.id)
    return { controller, browser, model, geometry, index }
  }

  it('拖到另一区域的标签栏 → 跨区移动，区域数不变', () => {
    const { controller, browser, index } = setup()
    const target = controller.split('main', 'right')!
    const model = controller.model.value
    const geometry = controller.geometry.value
    const rect = geometry.areas[target].rect
    // 目标区域是纵向轴（空区域默认 vertical），左侧 36px 带就是它的标签栏。
    const plan = planTabDrop({
      geometry,
      model,
      point: { x: rect.x + 10, y: rect.y + 40 },
      source: { pane: 'main', index, surfaceId: browser.id },
    })
    expect(plan.kind).toBe('move')
    if (plan.kind !== 'move') return
    controller.moveTab(plan.from, plan.to)
    expect(Object.keys(controller.state.panes)).toHaveLength(2)
    expect(controller.state.panes[target].tabs.map(tab => tab.id)).toContain(browser.id)
    expect(controller.state.panes.main.tabs.map(tab => tab.id)).not.toContain(browser.id)
  })

  it('拖到区域右边缘 → 区域数 +1，被拖标签跟着新区域走，源区域不残留', () => {
    const { controller, browser, index } = setup()
    const model = controller.model.value
    const geometry = controller.geometry.value
    const plan = planTabDrop({
      geometry,
      model,
      point: { x: 998, y: 300 },
      source: { pane: 'main', index, surfaceId: browser.id },
    })
    expect(plan.kind).toBe('split')
    if (plan.kind !== 'split') return
    expect(plan.edge).toBe('right')
    const created = controller.split(plan.pane, plan.edge)!
    expect(created).toBeTruthy()
    controller.moveTab(plan.from, { pane: created, index: 0 })
    expect(Object.keys(controller.state.panes)).toHaveLength(2)
    expect(controller.state.panes[created].tabs.map(tab => tab.id)).toEqual([browser.id])
    expect(controller.state.panes.main.tabs.map(tab => tab.id)).not.toContain(browser.id)
  })

  it('拖到同区左侧空处（标签栏） → 排序变化，区域数不变', () => {
    const { controller, browser } = setup()
    const before = controller.state.panes.main.tabs.map(tab => tab.id)
    const agentId = before[0]
    const model = controller.model.value
    const geometry = controller.geometry.value
    const plan = planTabDrop({
      geometry,
      model,
      point: { x: 10, y: 40 },
      source: { pane: 'main', index: 0, surfaceId: agentId },
    })
    expect(plan.kind).toBe('reorder')
    if (plan.kind !== 'reorder') return
    controller.reorderTab(plan.pane, plan.from, plan.to)
    expect(Object.keys(controller.state.panes)).toHaveLength(1)
    // agent 被挪到末尾，browser 顶到第一位。
    expect(controller.state.panes.main.tabs.map(tab => tab.id)).toEqual([browser.id, agentId])
  })

  it('拖动中 interactionPhase === draggingTab，松手后回到 idle', () => {
    const { controller } = setup()
    const machine = createTabDragMachine({
      begin: () => controller.beginInteraction('draggingTab'),
      end: commit => controller.endInteraction(commit),
    })
    machine.down({ pane: 'main', index: 0, surfaceId: 'x' }, { x: 100, y: 100 })
    expect(machine.phase).toBe('pending')
    machine.move({ x: 100 + TAB_DRAG_THRESHOLD + 2, y: 100 })
    expect(machine.phase).toBe('dragging')
    expect(controller.interactionPhase.value).toBe('draggingTab')
    machine.up(() => {})
    expect(machine.phase).toBe('idle')
    expect(controller.interactionPhase.value).toBe('idle')
  })

  it('拖动距离 <4px 视为点击：不进入 dragging，也不发生移动', () => {
    const { controller } = setup()
    const before = controller.state.panes.main.tabs.map(tab => tab.id)
    const machine = createTabDragMachine({
      begin: () => controller.beginInteraction('draggingTab'),
      end: commit => controller.endInteraction(commit),
    })
    machine.down({ pane: 'main', index: 0, surfaceId: 'x' }, { x: 100, y: 100 })
    // 3px：仍在 pending，网页还没让位。
    expect(machine.move({ x: 102, y: 101 })).toBe('pending')
    expect(controller.interactionPhase.value).toBe('idle')
    machine.up(undefined)
    expect(machine.phase).toBe('idle')
    expect(controller.state.panes.main.tabs.map(tab => tab.id)).toEqual(before)
  })

  it('轻微抖动（6px）不进入拖拽，且距边缘 30px 不误触发分屏', () => {
    const events: string[] = []
    const machine = createTabDragMachine({
      begin: () => events.push('begin'),
      end: () => events.push('end'),
    })
    machine.down({ pane: 'main', index: 0, surfaceId: 'agent-main' }, { x: 100, y: 18 })
    expect(machine.move({ x: 106, y: 20 })).toBe('pending')
    expect(events).toEqual([])
    machine.up()

    const { controller, browser, index } = setup()
    const plan = planTabDrop({
      geometry: controller.geometry.value,
      model: controller.model.value,
      point: { x: 965, y: 300 },
      source: { pane: 'main', index, surfaceId: browser.id },
    })
    expect(plan.kind).not.toBe('split')

    // 拖到页眉以上（标题栏 y < 0）或页眉内上边缘时不触发分屏或浮窗
    expect(planTabDrop({
      geometry: controller.geometry.value,
      model: controller.model.value,
      point: { x: 300, y: -10 },
      source: { pane: 'main', index, surfaceId: browser.id },
    })).toEqual({ kind: 'none' })
    expect(planTabDrop({
      geometry: controller.geometry.value,
      model: controller.model.value,
      point: { x: 300, y: 12 },
      source: { pane: 'main', index, surfaceId: browser.id },
    }).kind).not.toBe('split')
  })
})
