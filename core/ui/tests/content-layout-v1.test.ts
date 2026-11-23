import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ROW_FILL_INSET, fusionGeometry, fusionSeamGap, NO_FUSION, createFusionWriter, type FusionGeometry } from '../src/composables/sessionFusion'

describe('Agent 纵向融合：连接处几何', () => {
  it('没有选中行时不画', () => {
    expect(fusionGeometry(null, 240)).toEqual(NO_FUSION)
    expect(fusionGeometry({ top: 10, bottom: 10, right: 200 }, 240).visible).toBe(false)
  })

  it('高度取行的上下沿，铺设量止于会话栏内缘（扣掉行高亮自身的外扩）', () => {
    const geometry = fusionGeometry({ top: 120, bottom: 154, right: 214 }, 240)
    // user:“标签出去了…高亮块右侧伸出了侧栏边界，在侧栏与主区之间露出一截突兀的深色方块”+
    // (行高亮的 ::before 自己已经比行盒外扩 ROW_FILL_INSET=8px，所以铺设量 = 240 − (214 + 8) = 18；
    //  以前直接拿 240 − 214 = 26，多铺出去的这 8px 正是悬在缝里的那块深色)。
    expect(geometry).toEqual({ visible: true, top: 120, height: 34, rowBleed: 18 })
  })

  it('行已经超过会话栏右缘时不出现负的铺设量', () => {
    expect(fusionGeometry({ top: 0, bottom: 34, right: 300 }, 240).rowBleed).toBe(0)
  })

  // user:“补两条断言：选中行右缘不超过侧栏矩形；同栏内两种行类型的右缘相等”+
  // (这两条正是截图里看出来的两处：一块伸出资栏、一块没顶到边。)
  it('选中行填充止于侧栏内缘：行右缘 + 外扩 + 铺设量 = 内缘，不多铺一丝', () => {
    const drawerInnerRight = 240
    const row = { top: 120, bottom: 154, right: 214 }
    const geometry = fusionGeometry(row, drawerInnerRight)
    const rowFillRight = row.right + ROW_FILL_INSET + geometry.rowBleed
    expect(rowFillRight).toBe(drawerInnerRight)
    expect(rowFillRight).toBeLessThanOrEqual(drawerInnerRight)
  })

  it('侧栏窄一点时同样止于内缘（不写死内边距，只认实测内缘）', () => {
    const row = { top: 120, bottom: 154, right: 214 }
    const narrow = fusionGeometry(row, 232)
    expect(row.right + ROW_FILL_INSET + narrow.rowBleed).toBe(232)
    // 行盒比内缘还宽时不许往回缩成负数。
    expect(narrow.rowBleed).toBeGreaterThanOrEqual(0)
  })

  it('同一栏里「最近」与项目会话右缘相等 ⇒ 铺设量相等', () => {
    // 「最近」在 .conversation-items 里、项目会话在 .project-block > .conversation-list 里；
    // 两条容器现在共用同一套横向几何，所以右缘相同，铺设量只由右缘与内缘决定，必然相等。
    const drawerInnerRight = 240
    const recent = fusionGeometry({ top: 645, bottom: 679, right: 214 }, drawerInnerRight)
    const project = fusionGeometry({ top: 300, bottom: 334, right: 214 }, drawerInnerRight)
    expect(recent.rowBleed).toBe(project.rowBleed)
  })

  it('两种行容器共用同一套横向几何（源码锁，防止某一边又长出内边距）', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/session-sidebar.css'), 'utf8')
    expect(css).toMatch(/\.conversation-list,\s*\.sidebar-section \.conversation-items \{[^}]*padding-left: 0[^}]*padding-right: 0[^}]*margin-inline: 0/)
  })
})

// user:“加一条单测：同一几何连续测量 N 次只写 1 次变量（用假 rAF）”+
// (这条回路曾经是每帧无条件写自定义属性 → 全树标脏 → 强制全量布局，dev 下表现为界面未响应。
//  这里用假 rAF 精确锁住三件事：同一帧合并、数值相等短路、卸载后彻底停。)
function fakeClock() {
  const queue: Array<() => void> = []
  return {
    raf: (callback: () => void) => { queue.push(callback); return queue.length },
    cancelRaf: () => { queue.length = 0 },
    run() { queue.splice(0).forEach(callback => callback()) },
    get pending() { return queue.length },
  }
}

describe('连接处写入器：合并 + 值相等短路 + 可停', () => {
  const geometry = (patch: Partial<FusionGeometry> = {}): FusionGeometry => ({ visible: true, top: 120, height: 34, rowBleed: 26, ...patch })

  it('同一帧内多次请求只量一次，同一几何连续测量 N 次只写 1 次', () => {
    const clock = fakeClock()
    let measures = 0
    const writes: Array<FusionGeometry | null> = []
    const writer = createFusionWriter<FusionGeometry>({
      measure: () => { measures += 1; return geometry() },
      write: value => writes.push(value),
      raf: clock.raf,
      cancelRaf: clock.cancelRaf,
    })
    for (let i = 0; i < 8; i += 1) writer.schedule()
    expect(measures).toBe(0)
    expect(clock.pending).toBe(1)
    clock.run()
    expect(measures).toBe(1)
    expect(writes).toHaveLength(1)
    // 同一几何再来 5 帧：只读不写。
    for (let i = 0; i < 5; i += 1) { writer.schedule(); clock.run() }
    expect(measures).toBe(6)
    expect(writes).toHaveLength(1)
    writer.dispose()
  })

  it('几何真的变了才写第二次；invalidate 后同几何也写', () => {
    const clock = fakeClock()
    let current = geometry()
    const writes: Array<FusionGeometry | null> = []
    const writer = createFusionWriter<FusionGeometry>({
      measure: () => current,
      write: value => writes.push(value),
      raf: clock.raf,
      cancelRaf: clock.cancelRaf,
    })
    writer.schedule(); clock.run()
    current = geometry({ top: 160 })
    writer.schedule(); clock.run()
    expect(writes.map(entry => entry?.top)).toEqual([120, 160])
    writer.schedule(); clock.run()
    expect(writes).toHaveLength(2)
    writer.invalidate()
    writer.schedule(); clock.run()
    expect(writes).toHaveLength(3)
    writer.dispose()
  })

  it('量不到东西时只写一次“不画”，不会每帧重复写', () => {
    const clock = fakeClock()
    const writes: Array<FusionGeometry | null> = []
    const writer = createFusionWriter<FusionGeometry>({
      measure: () => null,
      write: value => writes.push(value),
      raf: clock.raf,
      cancelRaf: clock.cancelRaf,
    })
    for (let i = 0; i < 4; i += 1) { writer.schedule(); clock.run() }
    expect(writes).toEqual([null])
    writer.dispose()
  })

  it('dispose 后不再量也不再写，挂起的帧被取消', () => {
    const clock = fakeClock()
    let measures = 0
    const writes: Array<FusionGeometry | null> = []
    const writer = createFusionWriter<FusionGeometry>({
      measure: () => { measures += 1; return geometry() },
      write: value => writes.push(value),
      raf: clock.raf,
      cancelRaf: clock.cancelRaf,
    })
    writer.schedule()
    writer.dispose()
    clock.run()
    writer.schedule(); clock.run()
    expect(measures).toBe(0)
    expect(writes).toHaveLength(0)
  })
})

// user:“会话栏与主区仍是两个孤立容器，没连起来…补一条断言：选中行右缘与内容区左缘之间的缝隙宽度为 0”+
// (数值取真实几何：会话栏右缘 240、行右缘 214（内边距 26）、主区左缘 243（3px 中缝）、连接层 inset 12)。
describe('连接处：选中行与内容区之间不留缝', () => {
  const seam = (patch: Partial<Parameters<typeof fusionSeamGap>[0]> = {}) => ({
    rowRight: 214, rowBleed: 26, plateLeft: 240, plateWidth: 15, contentLeft: 243, ...patch,
  })

  it('正常几何下缝隙为 0（行填充接上连接层，连接层盖过 3px 中缝并伸进内容区）', () => {
    expect(fusionSeamGap(seam())).toBe(0)
  })

  it('连接层被关掉（inset 0 或没铺）时会露出缝隙——这条能抓住回归', () => {
    expect(fusionSeamGap(seam({ plateWidth: 0 }))).toBeGreaterThan(0)
    expect(fusionSeamGap(seam({ rowBleed: 0, plateWidth: 3 }))).toBe(0)   // 只靠连接层也能接上
    // 行填充为 0、连接层也为 0 时，从行右缘 214 到主区左缘 243 仍差 3px（中缝）
    expect(fusionSeamGap(seam({ rowBleed: 0, plateWidth: 0 }))).toBe(3)
  })
})
