/**
 * Ping 工作台纯逻辑：环几何、菜单树、配置归一化。
 *
 * user:“一级完整环；二级、三级是局部同心弧形环带”+
 * “长文本截断但悬停可显示全文，文字跟随各自扇区角度”+
 * “最多三级”“模拟绝不发送真实 Agent 消息”
 */
import { describe, expect, it } from 'vitest'
import { defaultPingSectors, type PingSectorConfig } from '@/pet/config.ts'
import {
  arcAtPoint,
  buildRingEditorGeometry,
  polar,
  truncateLabel,
} from '@/pet/ping/editorGeometry.ts'
import {
  buildPingTree,
  collectSubtreeIds,
  flattenTree,
  movePingSector,
  movePingSectorBeside,
  pingNodeDepth,
  pingSubtreeHeight,
  reparentPingSector,
} from '@/pet/ping/editorTree.ts'
import { defaultPingConfig, normalizePingConfig } from '@/pet/pingConfigRepository.ts'

function sectors(): PingSectorConfig[] {
  return defaultPingSectors().map(sector => ({ ...sector, prompt: sector.prompt }))
}

describe('Ping 环工作台几何', () => {
  it('一级每个启用项都有独立扇区，角度按顺序连续', () => {
    const list = sectors()
    const geometry = buildRingEditorGeometry(list, { radius: 132, ringWidth: 14 })
    expect(geometry.root.arcs).toHaveLength(list.filter(item => item.enabled && !item.group).length)
    for (const arc of geometry.root.arcs) {
      expect(arc.path.startsWith('M')).toBe(true)
      expect(arc.end).toBeGreaterThan(arc.start)
      expect(arc.rotation).toBeCloseTo(((arc.start + arc.end) / 2) * 180 / Math.PI, 4)
    }
    const ordered = [...geometry.root.arcs].sort((a, b) => a.start - b.start)
    for (let index = 1; index < ordered.length; index += 1) {
      expect(ordered[index].start).toBeGreaterThanOrEqual(ordered[index - 1].end)
    }
  })

  it('选中项的二级子环在同心的外圈，跨度受上下限约束', () => {
    const root = sectors()[0]
    const childSector: PingSectorConfig = {
      id: 'child-1', label: '子项', icon: '·', kind: 'custom', color: '#fff', enabled: true, group: root.id,
    }
    const list = [
      { ...root, kind: 'subring' as const, subring: root.id },
      childSector,
    ]
    const geometry = buildRingEditorGeometry(list, {
      radius: 120,
      ringWidth: 12,
      selectedId: root.id,
    })
    expect(geometry.child).not.toBeNull()
    expect(geometry.child!.inner).toBeGreaterThan(geometry.root.outer)
    expect(geometry.child!.arcs).toHaveLength(1)
    expect(geometry.child!.arcs[0].id).toBe('child-1')
    const span = geometry.child!.arcs[0].end - geometry.child!.arcs[0].start
    expect(span).toBeGreaterThan(0)
    expect(span).toBeLessThanOrEqual(2.1)
  })

  it('选中三级项时沿父链生成最多三层同心环带', () => {
    const list: PingSectorConfig[] = [
      { id: 'root', label: '工具', icon: '＋', kind: 'subring', subring: 'tools', color: '#fff', enabled: true },
      { id: 'child', label: '截图', icon: '框', kind: 'subring', subring: 'shot', color: '#fff', enabled: true, group: 'tools' },
      { id: 'grand', label: '问号', icon: '?', kind: 'question', color: '#fff', enabled: true, group: 'shot' },
      { id: 'sibling', label: '其他', icon: '·', kind: 'custom', color: '#fff', enabled: true, group: 'tools' },
    ]
    const geometry = buildRingEditorGeometry(list, { radius: 120, ringWidth: 12, selectedId: 'grand' })
    expect(geometry.bands).toHaveLength(3)
    expect(geometry.bands[1].arcs.map(arc => arc.id)).toEqual(['child', 'sibling'])
    expect(geometry.bands[2].arcs.map(arc => arc.id)).toEqual(['grand'])
    expect(geometry.bands[2].inner).toBeGreaterThan(geometry.bands[1].outer)
  })

  it('沙盒按坐标命中的是所在扇区，中心死区/环外不命中', () => {
    const geometry = buildRingEditorGeometry(sectors(), { radius: 132, ringWidth: 14 })
    const first = geometry.root.arcs[0]
    const mid = polar(geometry.cx, geometry.cy, geometry.radius, (first.start + first.end) / 2)
    expect(arcAtPoint(geometry.root, geometry.cx, geometry.cy, mid.x, mid.y)?.id).toBe(first.id)
    expect(arcAtPoint(geometry.root, geometry.cx, geometry.cy, geometry.cx, geometry.cy)).toBeNull()
    const outside = polar(geometry.cx, geometry.cy, geometry.radius + 500, 0)
    expect(arcAtPoint(geometry.root, geometry.cx, geometry.cy, outside.x, outside.y)).toBeNull()
  })

  it('长标签截断但保留完整文本', () => {
    expect(truncateLabel('短', 8)).toBe('短')
    expect(truncateLabel('这是一个很长的菜单标签', 8)).toHaveLength(8)
    const geometry = buildRingEditorGeometry([
      { id: 'long', label: '这是一个很长的菜单标签', icon: '?', kind: 'question', color: '#fff', enabled: true },
    ], { radius: 100, ringWidth: 12 })
    expect(geometry.root.arcs[0].label.endsWith('…')).toBe(true)
    expect(geometry.root.arcs[0].fullLabel).toBe('这是一个很长的菜单标签')
  })
})

describe('Ping 菜单树', () => {
  const root: PingSectorConfig = {
    id: 'root', label: '工具', icon: '＋', kind: 'subring', subring: 'tools', color: '#fff', enabled: true,
  }
  const child: PingSectorConfig = {
    id: 'child', label: '截图', icon: '框', kind: 'select', color: '#fff', enabled: true, group: 'tools',
  }
  const sibling: PingSectorConfig = {
    id: 'sibling', label: '另一个', icon: '·', kind: 'custom', color: '#fff', enabled: true, group: 'tools',
  }
  const grandchild: PingSectorConfig = {
    id: 'grand', label: '三级', icon: '·', kind: 'custom', color: '#fff', enabled: true, group: 'child',
  }

  it('按 group/subring 建树，最多三级', () => {
    const tree = buildPingTree([root, child, sibling, grandchild])
    expect(tree).toHaveLength(1)
    expect(tree[0].children.map(node => node.sector.id)).toEqual(['child', 'sibling'])
    expect(tree[0].children[0].children.map(node => node.sector.id)).toEqual(['grand'])
    expect(flattenTree(tree).map(node => node.depth)).toEqual([1, 2, 3, 2])
  })

  it('删除父项会带走整棵子树，但不会误删兄弟', () => {
    const ids = collectSubtreeIds([root, child, sibling, grandchild], 'child')
    expect(ids).toEqual(new Set(['child', 'grand']))
    const rootIds = collectSubtreeIds([root, child, sibling, grandchild], 'root')
    expect(rootIds).toEqual(new Set(['root', 'child', 'sibling', 'grand']))
  })

  it('拖动可同层排序，并拒绝跨层排序（需显式拖入父项）', () => {
    const reordered = movePingSectorBeside([root, child, sibling, grandchild], 'sibling', 'child', 'before')
    expect(reordered.map(sector => sector.id)).toEqual(['root', 'sibling', 'child', 'grand'])
    expect(movePingSectorBeside([root, child, sibling], 'sibling', 'root', 'after')).toHaveLength(3)
  })

  it('拖到某行可成为子项，并阻止超过三级/拖进自己子树', () => {
    const leaf: PingSectorConfig = { id: 'leaf', label: '叶子', icon: '·', kind: 'custom', color: '#fff', enabled: true }
    const moved = reparentPingSector([root, child, sibling, grandchild, leaf], 'leaf', 'child')
    expect(moved.error).toBe('')
    expect(moved.sectors.find(sector => sector.id === 'leaf')?.group).toBe('child')
    expect(pingNodeDepth(moved.sectors, 'leaf')).toBe(3)
    // 再往下会到第四级。
    const tooDeep = reparentPingSector(moved.sectors, 'sibling', 'leaf')
    expect(tooDeep.error).toContain('最多')
    const cycle = reparentPingSector([root, child, sibling, grandchild], 'root', 'grand')
    expect(cycle.error).toContain('自己的子项')
    expect(pingSubtreeHeight([root, child, sibling, grandchild], 'root')).toBe(3)
  })

  it('上移/下移只交换同一父级的相邻项', () => {
    const moved = movePingSector([root, child, sibling, grandchild], 'sibling', -1)
    expect(moved.map(sector => sector.id)).toEqual(['root', 'sibling', 'child', 'grand'])
    expect(movePingSector(moved, 'sibling', -1)).toBe(moved)
  })
})

describe('Ping 配置归一化', () => {
  it('默认独立启用、尊重菜单顺序，并被旧配置迁移补齐', () => {
    const config = defaultPingConfig()
    expect(config.enabled).toBe(true)
    expect(config.autoPlaceSwitch).toBe(true)
    const migrated = normalizePingConfig({ hotkey: 'Ctrl+Alt+P' })
    expect(migrated.enabled).toBe(true)
    expect(migrated.autoPlaceSwitch).toBe(true)
  })

  it('旧配置缺少 enabled 时补 true，并保留自定义扇区', () => {
    const next = normalizePingConfig({
      hotkey: 'Ctrl+Alt+P',
      sectors: [{ id: 'x', label: 'X', icon: 'X', kind: 'custom', color: '#fff', enabled: true }],
    })
    expect(next.enabled).toBe(true)
    expect(next.hotkey).toBe('Ctrl+Alt+P')
    expect(next.sectors.some(sector => sector.id === 'x')).toBe(true)
  })
})

describe('设置入口与动作编辑规则', () => {
  it('设置菜单同时存在独立的 pet 与 ping 项', async () => {
    const { CORE_SETTINGS_SECTIONS } = await import('@/components/settingsSections.ts')
    const ids = CORE_SETTINGS_SECTIONS.map(section => section.id)
    expect(ids).toContain('pet')
    expect(ids).toContain('ping')
    expect(ids.indexOf('pet')).not.toBe(ids.indexOf('ping'))
  })

  it('动作 ID 稳定、单图静态、多图序列帧', async () => {
    const { clipForSources, slugActionName, uniqueActionId } = await import('@/pet/actionEditing.ts')
    expect(slugActionName('挥 手')).toBe('挥-手')
    expect(uniqueActionId(['walk', 'walk-2'], 'walk')).toBe('walk-3')
    expect(clipForSources(['a.png'])).toEqual({ type: 'static', source: 'a.png' })
    expect(clipForSources(['a.png', 'b.png'])).toMatchObject({ type: 'frames', sources: ['a.png', 'b.png'] })
  })

  it('被命中区引用的动作和 idle 不能删除', async () => {
    const { actionRemovalError } = await import('@/pet/actionEditing.ts')
    const hitboxes = [{
      id: 'head', name: '头', x: 0, y: 0, width: 1, height: 1,
      action: 'interact', doubleAction: 'wave', enabled: true,
    }]
    expect(actionRemovalError('idle', { idle: {} }, hitboxes)).toContain('待机')
    expect(actionRemovalError('wave', { wave: {} }, hitboxes)).toContain('命中区')
    expect(actionRemovalError('walk', { walk: {} }, hitboxes)).toBeNull()
  })
})
