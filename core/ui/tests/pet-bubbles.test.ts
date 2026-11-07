/**
 * 多气泡与遮挡的纯逻辑验收。
 *
 * user:“同时存在 10 个以上未处理审批时不会丢失”+
 * “多气泡可独立展开、折叠、同时显示”+
 * “气泡二维避让、跟随、屏幕边界约束成立”+
 * “重叠窗口遮挡采用正确的区域计算”+
 * (这里不挂 DOM、不做源码字符串断言：直接验证状态与几何函数的行为。)
 */
import { describe, expect, it } from 'vitest'
import {
  MAX_NOTIFICATIONS,
  expandBubble,
  foldAllBubbles,
  foldBubble,
  pendingBubbleCount,
  pruneBubbles,
  reconcileSessionRequests,
  requestBubbleId,
  resolveBubbleState,
  toggleBubbleExpanded,
  upsertBubble,
  type BubbleInput,
  type BubbleState,
} from '@/pet/ui/bubbleStore.ts'
import { layoutBubbles, type BubbleLayoutItem } from '@/pet/ui/bubbleLayout.ts'
import { subtractRect, unionRects } from '@/pet/render/occlusion.ts'
import { turnCompletionNotice } from '@/pet/agent/turnNotice.ts'
import { isDoubleClick, isPetDrag, shouldStartPetGesture } from '@/pet/ui/pointerGesture.ts'
import { clampToMonitors } from '@/pet/engine/monitors.ts'

function request(serial: number, overrides: Partial<BubbleInput> = {}): BubbleInput {
  return {
    id: requestBubbleId('s1', `req-${serial}`),
    petId: 'pet-1',
    sessionId: 's1',
    kind: 'actionable',
    title: '需要你的批准',
    subject: `请求 ${serial}`,
    body: '',
    requestId: `req-${serial}`,
    ...overrides,
  }
}

function addAll(inputs: BubbleInput[], maxAutoExpanded = 1): BubbleState[] {
  let list: BubbleState[] = []
  let now = 1000
  for (const input of inputs) {
    list = upsertBubble(list, input, { now: now++, maxAutoExpanded })
  }
  return list
}

describe('未处理请求可靠性', () => {
  it('15 条审批全部保留，不会被数量上限截断', () => {
    const list = addAll(Array.from({ length: 15 }, (_, index) => request(index)))
    expect(list).toHaveLength(15)
    expect(pendingBubbleCount(list)).toBe(15)
  })

  it('标题相同的不同请求不会被误判为重复', () => {
    const list = addAll(Array.from({ length: 5 }, (_, index) => request(index, {
      title: '需要你的批准',
      subject: '部署到生产环境',
    })))
    expect(list).toHaveLength(5)
    expect(new Set(list.map(bubble => bubble.id)).size).toBe(5)
  })

  it('同一 requestId 更新原气泡，不重复创建', () => {
    let list = addAll([request(1)])
    list = upsertBubble(list, request(1, { subject: '更完整的标题', options: [{ id: 'approve', label: '允许' }] }))
    expect(list).toHaveLength(1)
    expect(list[0].subject).toBe('更完整的标题')
    expect(list[0].options).toHaveLength(1)
  })

  it('默认只自动展开一条；手动展开多条不会被自动上限压回去', () => {
    let list = addAll(Array.from({ length: 4 }, (_, index) => request(index)), 1)
    expect(list.filter(bubble => bubble.expanded)).toHaveLength(1)
    list = expandBubble(list, list[0].id)
    list = expandBubble(list, list[1].id)
    list = expandBubble(list, list[2].id)
    expect(list.filter(bubble => bubble.expanded)).toHaveLength(4)
    // 新请求到达只收起「自动展开」的，用户手动展开的三条保持展开。
    list = upsertBubble(list, request(9), { now: 9999, maxAutoExpanded: 1 })
    expect(list.filter(bubble => bubble.expanded && bubble.userExpanded)).toHaveLength(3)
    expect(list.find(bubble => bubble.requestId === 'req-9')?.expanded).toBe(true)
    expect(list.find(bubble => bubble.requestId === 'req-9')?.userExpanded).toBe(false)
  })

  it('silent 策略保留入口但不自动展开', () => {
    const list = upsertBubble([], request(1, { expand: false }), { maxAutoExpanded: 1 })
    expect(list).toHaveLength(1)
    expect(list[0].expanded).toBe(false)
    expect(pendingBubbleCount(list)).toBe(1)
  })

  it('折叠不等于关闭：待处理数量不变，输入内容由组件草稿独立保存', () => {
    let list = addAll([request(1)])
    list = foldBubble(list, list[0].id)
    expect(list[0].expanded).toBe(false)
    expect(pendingBubbleCount(list)).toBe(1)
    list = toggleBubbleExpanded(list, list[0].id)
    expect(list[0].expanded).toBe(true)
  })

  it('一键收起全部只改显示状态', () => {
    let list = addAll(Array.from({ length: 3 }, (_, index) => request(index)))
    list = expandBubble(list, list[0].id)
    list = expandBubble(list, list[1].id)
    list = foldAllBubbles(list)
    expect(list.every(bubble => !bubble.expanded)).toBe(true)
    expect(pendingBubbleCount(list)).toBe(3)
  })

  it('后端解决后连续缺席两轮才移除，避免瞬时抖动误删', () => {
    let list = addAll([request(1), request(2)])
    list = reconcileSessionRequests(list, 's1', ['req-2'])
    expect(pendingBubbleCount(list)).toBe(2)
    list = reconcileSessionRequests(list, 's1', ['req-2'])
    expect(list.find(bubble => bubble.requestId === 'req-1')?.resolved).toBe(true)
    expect(pendingBubbleCount(list)).toBe(1)
    // 下一次真实轮询会 upsert 重新出现的请求：已解决气泡原地复活。
    list = upsertBubble(list, request(1))
    expect(pendingBubbleCount(list)).toBe(2)
    expect(list.find(bubble => bubble.requestId === 'req-1')?.absentPolls).toBe(0)
  })

  it('重新出现的请求会清零缺席计数', () => {
    let list = addAll([request(1)])
    list = reconcileSessionRequests(list, 's1', [])
    expect(list[0].absentPolls).toBe(1)
    list = reconcileSessionRequests(list, 's1', ['req-1'])
    expect(list[0].absentPolls).toBe(0)
    expect(list[0].resolved).toBe(false)
  })

  it('提交成功立即标记解决并退出待处理', () => {
    let list = addAll([request(1)])
    list = resolveBubbleState(list, list[0].id)
    expect(pendingBubbleCount(list)).toBe(0)
  })

  it('普通通知可限流，但永远不会挤掉待处理审批', () => {
    let list: BubbleState[] = []
    for (let index = 0; index < 40; index += 1) {
      list = upsertBubble(list, {
        id: `notice:${index}`,
        petId: '',
        sessionId: 's1',
        kind: 'notification',
        title: '任务完成',
        body: 'done',
      }, { now: 1000 + index })
    }
    list = upsertBubble(list, request(1), { now: 2000 })
    const pruned = pruneBubbles(list, { now: 3000, maxNotifications: MAX_NOTIFICATIONS })
    expect(pruned.filter(bubble => bubble.kind === 'notification')).toHaveLength(MAX_NOTIFICATIONS)
    expect(pruned.some(bubble => bubble.requestId === 'req-1')).toBe(true)
  })
})

describe('气泡二维布局', () => {
  const viewport = { width: 1280, height: 800 }

  function items(count: number, anchorX = 640, anchorY = 300): BubbleLayoutItem[] {
    return Array.from({ length: count }, (_, index) => ({
      id: `b${index}`,
      width: 240,
      height: 150,
      anchorX,
      anchorY,
      petHeight: 160,
      priority: 100 - index,
    }))
  }

  it('多个气泡不重叠且左右散开，不是纵向列表', () => {
    const placements = layoutBubbles(items(4), { viewport })
    const values = [...placements.values()]
    expect(values).toHaveLength(4)
    for (let a = 0; a < values.length; a += 1) {
      for (let b = a + 1; b < values.length; b += 1) {
        const left = values[a]
        const right = values[b]
        const overlapX = Math.min(left.left + left.width, right.left + right.width) - Math.max(left.left, right.left)
        const overlapY = Math.min(left.top + left.height, right.top + right.height) - Math.max(left.top, right.top)
        expect(overlapX <= 0 || overlapY <= 0, `气泡 ${a} 与 ${b} 重叠`).toBe(true)
      }
    }
    expect(new Set(values.map(value => value.left)).size).toBeGreaterThan(1)
  })

  it('手动展开 8 条时仍然互不遮挡（候选网格兜底）', () => {
    const placements = layoutBubbles(items(8), { viewport })
    const values = [...placements.values()]
    for (let a = 0; a < values.length; a += 1) {
      for (let b = a + 1; b < values.length; b += 1) {
        const left = values[a]
        const right = values[b]
        const overlapX = Math.min(left.left + left.width, right.left + right.width) - Math.max(left.left, right.left)
        const overlapY = Math.min(left.top + left.height, right.top + right.height) - Math.max(left.top, right.top)
        expect(overlapX <= 0 || overlapY <= 0, `气泡 ${a} 与 ${b} 重叠`).toBe(true)
        expect(left.left).toBeGreaterThanOrEqual(8)
        expect(left.top).toBeGreaterThanOrEqual(8)
        expect(left.left + left.width).toBeLessThanOrEqual(viewport.width - 8)
        expect(left.top + left.height).toBeLessThanOrEqual(viewport.height - 8)
      }
    }
  })

  it('靠右边缘时自动翻到左侧，绝不溢出屏幕', () => {
    const placements = layoutBubbles(items(2, 1270, 300), { viewport })
    for (const value of placements.values()) {
      expect(value.left).toBeGreaterThanOrEqual(8)
      expect(value.left + value.width).toBeLessThanOrEqual(viewport.width - 8)
      expect(value.top).toBeGreaterThanOrEqual(8)
      expect(value.top + value.height).toBeLessThanOrEqual(viewport.height - 8)
    }
  })

  it('避开桌宠本体（宠物矩形作为障碍）', () => {
    const pet = { x: 560, y: 300, width: 160, height: 200 }
    const placements = layoutBubbles(items(1), { viewport, obstacles: [pet], simplify: true })
    const value = [...placements.values()][0]
    const overlapX = Math.min(value.left + value.width, pet.x + pet.width) - Math.max(value.left, pet.x)
    const overlapY = Math.min(value.top + value.height, pet.y + pet.height) - Math.max(value.top, pet.y)
    expect(overlapX <= 0 || overlapY <= 0).toBe(true)
  })

  it('桌宠轻微移动时保持原位置，不来回换边', () => {
    const first = layoutBubbles(items(1, 640, 300), { viewport })
    const before = [...first.values()][0]
    const moved = items(1, 644, 302)
    moved[0].previous = { left: before.left, top: before.top }
    const after = [...layoutBubbles(moved, { viewport }).values()][0]
    expect(Math.abs(after.left - before.left)).toBeLessThanOrEqual(6)
    expect(Math.abs(after.top - before.top)).toBeLessThanOrEqual(6)
  })
})

describe('任务完成通知来自真实回合状态迁移', () => {
  it('运行中 → 完成才通知', () => {
    expect(turnCompletionNotice(undefined, 'completed')).toBeNull()
    expect(turnCompletionNotice('completed', 'running')).toBeNull()
    expect(turnCompletionNotice('running', 'idle')).toBeNull()
    expect(turnCompletionNotice('running', 'completed')?.status).toBe('completed')
    expect(turnCompletionNotice('waiting', 'completed')?.status).toBe('completed')
  })

  it('失败与停止也来自终态迁移，并给出可读文案', () => {
    expect(turnCompletionNotice('running', 'failed')).toMatchObject({
      status: 'failed',
      title: '任务失败',
    })
    expect(turnCompletionNotice('interrupting', 'cancelled')).toMatchObject({
      status: 'cancelled',
      title: '任务已停止',
    })
  })

  it('启动快照直接是终态时不补发历史通知', () => {
    expect(turnCompletionNotice(undefined, 'failed')).toBeNull()
    expect(turnCompletionNotice(undefined, 'cancelled')).toBeNull()
  })
})

describe('鼠标手势判定', () => {
  it('右键不会开始左键抓取/点击', () => {
    expect(shouldStartPetGesture(0, false)).toBe(true)
    expect(shouldStartPetGesture(2, false)).toBe(false)
    expect(shouldStartPetGesture(1, false)).toBe(false)
  })

  it('按在卡片/收纳区上不会穿透成抓取桌宠', () => {
    expect(shouldStartPetGesture(0, true)).toBe(false)
  })

  it('移动超过阈值才算拖拽；双击按同一宠物与时间窗判定', () => {
    expect(isPetDrag(4)).toBe(false)
    expect(isPetDrag(8)).toBe(true)
    expect(isDoubleClick('pet-1', 'pet-1', 200)).toBe(true)
    expect(isDoubleClick('pet-1', 'pet-2', 200)).toBe(false)
    expect(isDoubleClick('pet-1', 'pet-1', 500)).toBe(false)
  })
})

describe('多显示器可视区域', () => {
  const monitors = [
    { x: 0, y: 0, width: 1920, height: 1080 },
    { x: 1920, y: 300, width: 1280, height: 720 },
  ]

  it('站在显示器内不动', () => {
    expect(clampToMonitors(monitors, 100, 500, 90).changed).toBe(false)
    expect(clampToMonitors(monitors, 2000, 500, 90).changed).toBe(false)
  })

  it('走进副屏上方空隙时拉回最近显示器', () => {
    const fixed = clampToMonitors(monitors, 2000, 100, 90)
    expect(fixed.changed).toBe(true)
    const inside = monitors.some(monitor => (
      fixed.x >= monitor.x
      && fixed.x <= monitor.x + monitor.width
      && fixed.y >= monitor.y
      && fixed.y <= monitor.y + monitor.height
    ))
    expect(inside).toBe(true)
  })

  it('右侧越界时拉回屏幕边缘，并标记需要清零速度', () => {
    const fixed = clampToMonitors(monitors, 4000, 500, 90)
    expect(fixed.changed).toBe(true)
    expect(fixed.x).toBe(3200)
    expect(fixed.clampedX).toBe(true)
  })
})

describe('遮挡面积与鼠标命中', () => {
  it('两个重叠窗口的面积只算一次', () => {
    const merged = unionRects([
      { x: 0, y: 0, width: 100, height: 100 },
      { x: 50, y: 0, width: 100, height: 100 },
    ])
    const total = merged.reduce((sum, rect) => sum + rect.width * rect.height, 0)
    expect(total).toBe(15000)
    expect(merged).toHaveLength(1)
    expect(merged[0]).toEqual({ x: 0, y: 0, width: 150, height: 100 })
  })

  it('重叠洞不会在 SVG evenodd 里互相抵消', () => {
    // 两个洞重叠后应合并成一个矩形，而不是两个互相抵消的洞。
    const merged = unionRects([
      { x: 0, y: 0, width: 40, height: 40 },
      { x: 20, y: 20, width: 40, height: 40 },
    ])
    expect(merged).toEqual([
      { x: 0, y: 0, width: 40, height: 20 },
      { x: 0, y: 20, width: 60, height: 20 },
      { x: 20, y: 40, width: 40, height: 20 },
    ])
  })

  it('命中矩形减去被遮挡部分，不可见区域不再拦截鼠标', () => {
    const pieces = subtractRect(
      { x: 0, y: 0, width: 100, height: 100 },
      [{ x: 20, y: 20, width: 40, height: 40 }],
    )
    const total = pieces.reduce((sum, rect) => sum + rect.width * rect.height, 0)
    expect(total).toBe(10000 - 1600)
    for (const piece of pieces) {
      const overlapX = Math.min(piece.x + piece.width, 60) - Math.max(piece.x, 20)
      const overlapY = Math.min(piece.y + piece.height, 60) - Math.max(piece.y, 20)
      expect(overlapX <= 0 || overlapY <= 0).toBe(true)
    }
  })
})
