import { describe, expect, it } from 'vitest'
import {
  PREFLIGHT_MIN_TOUCH,
  blockingIssues,
  checkTargetsAtWidth,
  collectIssues,
  scanShellWidths,
  type PreflightTarget,
} from '../src/themeStudio/preflight.ts'

/**
 * user:“发布前执行连续宽度扫描和关键节点可达性检查”+
 * (溢出与关键入口不可达要挡住发布；触控过小只提醒。)
 */

const shell = { left: 0, top: 0, width: 320, height: 800 }

function target(overrides: Partial<PreflightTarget> = {}): PreflightTarget {
  return {
    id: 'shell.sidebar',
    label: '会话列表',
    protection: 'editable',
    editableSize: true,
    rect: { left: 10, top: 10, width: 200, height: 300 },
    ...overrides,
  }
}

describe('发布前检查', () => {
  it('溢出报出方向与像素', () => {
    const issues = checkTargetsAtWidth({
      width: 320,
      shell,
      targets: [target({ rect: { left: 10, top: 10, width: 400, height: 300 } })],
    })
    expect(issues).toHaveLength(1)
    expect(issues[0].kind).toBe('overflow')
    expect(issues[0].message).toContain('右 90px')
  })

  it('同一个问题只报最窄的那次', () => {
    const issues = collectIssues([
      { width: 768, shell: { ...shell, width: 768 }, targets: [target({ rect: { left: 0, top: 0, width: 700, height: 100 } })] },
      { width: 320, shell, targets: [target({ rect: { left: 0, top: 0, width: 700, height: 100 } })] },
    ])
    expect(issues).toHaveLength(1)
    expect(issues[0].width).toBe(320)
  })

  it('关键入口量不到要阻断发布', () => {
    const issues = collectIssues([{
      width: 375,
      shell: { ...shell, width: 375 },
      targets: [target({ protection: 'protected', rect: { left: 0, top: 0, width: 0, height: 0 } })],
    }])
    expect(issues[0].kind).toBe('unreachable')
    expect(blockingIssues(issues)).toHaveLength(1)
  })

  it('触控区过小只提醒，不阻断', () => {
    const issues = collectIssues([{
      width: 320,
      shell,
      targets: [target({ editableSize: true, rect: { left: 10, top: 10, width: PREFLIGHT_MIN_TOUCH - 4, height: PREFLIGHT_MIN_TOUCH - 4 } })],
    }])
    expect(issues[0].kind).toBe('touch-target')
    expect(blockingIssues(issues)).toHaveLength(0)
  })

  it('干净目标没有问题', () => {
    const issues = collectIssues([{ width: 1440, shell: { ...shell, width: 1440 }, targets: [target()] }])
    expect(issues).toEqual([])
  })

  it('扫描按宽度取样并恢复原宽度', () => {
    const fakeShell = { style: { width: '1200px' }, offsetWidth: 1200 }
    const seen: number[] = []
    const samples = scanShellWidths(fakeShell, [1440, 375, 320], (width) => {
      seen.push(width)
      return { shell: { left: 0, top: 0, width, height: 800 }, targets: [] }
    })
    expect(seen).toEqual([1440, 375, 320])
    expect(samples.map((sample) => sample.width)).toEqual([1440, 375, 320])
    expect(fakeShell.style.width).toBe('1200px')
  })

  it('取样中途抛错也会恢复宽度', () => {
    const fakeShell = { style: { width: '1000px' }, offsetWidth: 1000 }
    expect(() => scanShellWidths(fakeShell, [320], () => {
      throw new Error('measure failed')
    })).toThrow('measure failed')
    expect(fakeShell.style.width).toBe('1000px')
  })
})
