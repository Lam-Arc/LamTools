/**
 * 生产 Ping 环的自定义同心二/三级。
 *
 * user:“一级、二级、三级展开时保留父项激活状态”+
 * “二三级是父扇区径向外侧的局部同心弧形环带”+
 * (设置页编辑器与生产环共用同一份 sectors；这里验证悬停展开与松键执行。)
 */
import { describe, expect, it, vi } from 'vitest'
import { createPingRuntime, type PingRuntimeDeps } from '@/pet/ping/usePingRuntime.ts'
import { defaultConfig, type PingSectorConfig } from '@/pet/config.ts'

function deps(overrides: Partial<PingRuntimeDeps> = {}): PingRuntimeDeps {
  const openSettings = vi.fn()
  const refreshTerrain = vi.fn(async () => {})
  return {
    config: defaultConfig(),
    overlay: { x: 0, y: 0, width: 1000, height: 1000, scale: 1 },
    cursor: { x: 500, y: 500 },
    getHost: () => null,
    getClient: () => null,
    save: () => {},
    report: () => {},
    notify: () => {},
    openSessionPicker: () => {},
    customActions: { openSettings, refreshTerrain },
    ...overrides,
  }
}

function nestedSectors(): PingSectorConfig[] {
  return [
    {
      id: 'tools', label: '工具', icon: '＋', kind: 'subring', subring: 'tools',
      color: '#C7A6FF', enabled: true,
    },
    {
      id: 'shot', label: '截图', icon: '框', kind: 'subring', subring: 'shot',
      color: '#8FD6FF', enabled: true, group: 'tools',
    },
    {
      id: 'refresh', label: '刷新地形', icon: '↻', kind: 'custom', action: 'refresh-l3',
      color: '#7ED6A5', enabled: true, group: 'shot',
    },
    {
      id: 'settings', label: '设置', icon: '⚙', kind: 'custom', action: 'settings',
      color: '#BFC7D5', enabled: true, group: 'tools',
    },
  ]
}

function pointAt(ring: { x: number; y: number }, radius: number, angle: number): { x: number; y: number } {
  // 生产环使用标准数学角（-π/2 = 正上方），不是编辑器预览的“上方为 0”。
  return {
    x: ring.x + Math.cos(angle) * radius,
    y: ring.y + Math.sin(angle) * radius,
  }
}

describe('生产 Ping 环的自定义同心层级', () => {
  it('悬停一级子菜单展开二级，松键执行叶子动作', async () => {
    const runtimeDeps = deps()
    const config = defaultConfig()
    config.ping.sectors = nestedSectors()
    runtimeDeps.config = config
    const ping = createPingRuntime(runtimeDeps)
    ping.openRing(500, 500)
    expect(ping.ring.sectors.map(sector => sector.id)).toEqual(['tools'])
    // 一级唯一项的中心在正上方。
    ping.onCursorMoved(500, 500 - 132)
    expect(ping.tiers.l2.visible).toBe(true)
    expect(ping.tiers.l2.source).toBe('custom')
    expect(ping.tiers.l2.sectors.map(sector => sector.id)).toEqual(['shot', 'settings'])
    // 悬停第一个二级项“截图”，它还有三级。
    const l2 = ping.tiers.l2
    const childAngle = l2.start + (l2.slots[0] || 0) / 2
    const childPoint = pointAt(ping.ring, l2.radius, childAngle)
    ping.onCursorMoved(childPoint.x, childPoint.y)
    expect(ping.tiers.l3.visible).toBe(true)
    expect(ping.tiers.l3.sectors.map(sector => sector.id)).toEqual(['refresh'])
    // 松开三级叶子：执行真实绑定的本地动作（不是切换会话）。
    const l3 = ping.tiers.l3
    const leafAngle = l3.start + (l3.slots[0] || 0) / 2
    const leafPoint = pointAt(ping.ring, l3.radius, leafAngle)
    ping.onCursorMoved(leafPoint.x, leafPoint.y)
    expect(ping.tiers.l3.hovered).toBe('refresh')
    await ping.commitRing(leafPoint.x, leafPoint.y)
    expect(runtimeDeps.customActions.refreshTerrain).toHaveBeenCalledTimes(1)
    expect(ping.ring.visible).toBe(false)
  })

  it('二级叶子不展开三级，松键执行自身', async () => {
    const runtimeDeps = deps()
    const config = defaultConfig()
    config.ping.sectors = nestedSectors()
    runtimeDeps.config = config
    const ping = createPingRuntime(runtimeDeps)
    ping.openRing(500, 500)
    ping.onCursorMoved(500, 500 - 132)
    const l2 = ping.tiers.l2
    const index = l2.sectors.findIndex(sector => sector.id === 'settings')
    const angle = l2.start + l2.slots.slice(0, index).reduce((sum, slot) => sum + slot, 0) + (l2.slots[index] || 0) / 2
    const point = pointAt(ping.ring, l2.radius, angle)
    ping.onCursorMoved(point.x, point.y)
    expect(ping.tiers.l3.visible).toBe(false)
    await ping.commitRing(point.x, point.y)
    expect(runtimeDeps.customActions.openSettings).toHaveBeenCalledTimes(1)
  })

  it('松开一级子菜单父项只收起，不重建整环', () => {
    const runtimeDeps = deps()
    const config = defaultConfig()
    config.ping.sectors = nestedSectors()
    runtimeDeps.config = config
    const ping = createPingRuntime(runtimeDeps)
    ping.openRing(500, 500)
    ping.onCursorMoved(500, 500 - 132)
    expect(ping.tiers.l2.visible).toBe(true)
    void ping.commitRing(500, 500 - 132)
    expect(ping.ring.visible).toBe(false)
  })
})
