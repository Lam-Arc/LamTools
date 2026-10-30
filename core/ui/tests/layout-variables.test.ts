import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * user:“先调查有什么规定了布局规则的值；然后把它全部都做成变量。
 *  不要再有写死的值和无法被改变的值”+
 * (布局几何统一走 --layout-* 覆盖链：会话抽屉宽度一变，主区域等派生位置自动跟随。)
 */
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')
const variablesCss = read('src/styles/variables.css')
const shellCss = read('src/styles/workspace-shell.css')
const splitCss = read('src/styles/split-workspace.css')
const titleBar = read('src/components/TitleBar.vue')
const registry = read('src/uiRegistry/registry.ts')

describe('布局规则变量统一', () => {
  // user:“就是为了适配这个编辑器，原有的层级数值你可以给它进行调整，让它更直观”+
  // (z 令牌按编辑器图层体系每 100 一层：背景→1、舞台→2、主表面→3、边缘→4、输入→5、浮层→6、模态→7、提示→8、全屏→9)
  it('层级令牌按每 100 一层重新分段', () => {
    const order = [
      '--z-background-info: 100',
      '--z-stage: 200',
      '--z-main-surface: 300',
      '--z-edge-trigger: 400',
      '--z-composer: 500',
      '--z-popover: 600',
      '--z-modal: 700',
      '--z-toast: 800',
      '--z-fullscreen: 900',
    ]
    for (const token of order) expect(variablesCss).toContain(token)
    const indexes = order.map((token) => variablesCss.indexOf(token))
    expect([...indexes].sort((left, right) => left - right)).toEqual(indexes)
  })
  // user:“我认为主区和分屏本质是一个容器”+(分屏是内容区的布局模式子节点，不是平级区域)
  it('分屏挂在内容区之下，是同一个容器的布局模式', () => {
    expect(registry).toMatch(/id: 'shell\.split',[\s\S]*?parent: 'shell\.main'/)
    expect(registry).toMatch(/id: 'shell\.main',[\s\S]*?label: '内容区'/)
  })

  it('分屏主面板宽度同样走布局变量覆盖链', () => {
    expect(splitCss).toContain('var(--layout-split-primary-width, var(--split-primary-width))')
  })
  it('侧栏宽度与标题栏高度都经过 --layout-* 覆盖链', () => {
    expect(variablesCss).toContain('--sidebar-width: var(--layout-sidebar-width')
    expect(variablesCss).toContain('--titlebar-offset: var(--layout-titlebar-height, var(--titlebar-native-height')
    // 断点档位同样被覆盖链包住，任何窗口宽度下编辑器变量都优先。
    expect(shellCss).toContain('--sidebar-width: var(--layout-sidebar-width, var(--sidebar-width-mid))')
    expect(shellCss).toContain('--sidebar-width: var(--layout-sidebar-width, var(--sidebar-width-full))')
  })

  it('右抽屉、竖栏、输入栏与下沿留白同样是可覆盖变量', () => {
    expect(shellCss).toContain('--right-drawer-width: var(--layout-right-drawer-width')
    expect(shellCss).toContain('--rail-width: var(--layout-rail-width')
    expect(shellCss).toContain('--composer-height: var(--layout-composer-height')
    expect(shellCss).toContain('--shell-bottom-inset: var(--layout-bottom-inset')
  })

  it('标题栏只登记原生高度，不再直接写死偏移变量', () => {
    expect(titleBar).toContain("'--titlebar-native-height'")
    expect(titleBar).not.toContain("style.setProperty('--titlebar-offset'")
  })
})
