import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { COMPOSER_MIN_WIDTH, composerBoxFor, composerColumnBox, composerColumnStyle, composerInsideColumn, type Box } from '../src/composer/composerColumn'

const read = (rel: string) => readFileSync(resolve(__dirname, rel), 'utf8')

// user:“补一条测试：给定主区矩形与分屏矩形，输入栏矩形必须完全落在主区内（用纯函数算，别靠肉眼）”+
// (数值取截图里的真实布局：主区从 x=46 起、宽 1200，右侧分屏 520 宽 → 主 pane 只剩 680)
const MAIN_REGION: Box = { x: 46, y: 36, width: 1200, height: 760 }
const AUX_PANE: Box = { x: 746, y: 36, width: 500, height: 760 }
const MAIN_PANE: Box = { x: 46, y: 36, width: 680, height: 760 }

describe('输入栏：必须落在主内容列内', () => {
  it('分屏时列是主 pane；没分屏时列是主区', () => {
    expect(composerColumnBox(MAIN_REGION, MAIN_PANE).width).toBe(680)
    expect(composerColumnBox(MAIN_REGION, null).width).toBe(1200)
  })

  it('分屏布局下输入栏完全在主 pane 内，不碰右侧分屏', () => {
    const column = composerColumnBox(MAIN_REGION, MAIN_PANE)
    const composer = composerBoxFor(column, { padding: 24, contentFill: 1040 })
    expect(composer.width).toBe(632)                       // 680 - 24*2
    expect(composer.x).toBe(70)                            // 居中：(680-632)/2 + 46
    expect(composerInsideColumn(column, composer)).toBe(true)
    expect(composer.x + composer.width).toBeLessThan(AUX_PANE.x)
  })

  it('回归：横跨整行的输入栏会被这条断言抓住', () => {
    const column = composerColumnBox(MAIN_REGION, MAIN_PANE)
    const runaway: Box = { x: MAIN_REGION.x, y: MAIN_REGION.y, width: MAIN_REGION.width, height: 120 }
    expect(composerInsideColumn(column, runaway)).toBe(false)
    expect(runaway.x + runaway.width).toBeGreaterThan(AUX_PANE.x)   // 正是截图里“压住辅助按钮”的情形
  })

  it('窄列：宽度跟着收到列宽以内，但不少于最小可用宽度', () => {
    const narrow = composerColumnBox(MAIN_REGION, { x: 46, y: 36, width: 300, height: 760 })
    const composer = composerBoxFor(narrow, { padding: 24, minWidth: COMPOSER_MIN_WIDTH })
    expect(composer.width).toBe(252)                       // 300 - 48
    expect(composerInsideColumn(narrow, composer)).toBe(true)
  })

  it('极窄列：宁可溢出一点也要保住最小宽度（不允许被压成缝）', () => {
    const tiny = composerColumnBox(MAIN_REGION, { x: 46, y: 36, width: 200, height: 760 })
    const composer = composerBoxFor(tiny, { padding: 24, minWidth: COMPOSER_MIN_WIDTH })
    expect(composer.width).toBe(COMPOSER_MIN_WIDTH)
    expect(composerInsideColumn(tiny, composer)).toBe(false)   // 这是已知退化，不是回归
  })
})

// user:“输入栏不得越过主区与分屏的边界；允许的最多是把「主区宽度 - 安全边距」”
describe('输入栏的 CSS 也按列变量定位（源码锁）', () => {
  const css = read('../src/styles/split-workspace.css')

  it('分屏规则优先用实测列变量，回退到几何变量，再用它们定位', () => {
    // user:“若主列几何变量缺失，就回退到主区容器的 getBoundingClientRect() 而不是 100vw”+
    // (实测值在前、几何变量在后：实测不到时才去拼 --split-primary-*，绝不直接落到 100vw)。
    expect(css).toContain('--composer-column-left: var(--composer-measured-left, calc(var(--main-left) + var(--split-primary-x, 0px)))')
    expect(css).toContain('--composer-column-width: var(--composer-measured-width, max(0px, var(--split-primary-width, 100vw)))')
    expect(css).toMatch(/max-width: calc\(var\(--composer-column-width/)
  })
})

// user:“两者之间有一条从上到下的明显缝隙（红框圈出，约 4px 宽、贯穿整个高度）”+
// (选 A：整条缝填成两侧同色、去掉相向的描边与内圆角；选中行的高亮由 .session-fusion 跨过)。
describe('会话栏与主区之间不再有缝（A 方案）', () => {
  const shellCss = read('../src/styles/workspace-shell.css')
  const shellVue = read('../src/components/WorkspaceShell.vue')

  it('缝隙填充层存在，且不吃指针、不参与布局', () => {
    expect(shellVue).toContain('data-session-seam')
    expect(shellCss).toMatch(/\.session-seam \{[^}]*pointer-events: none/)
    expect(shellCss).toMatch(/\.session-seam \{[^}]*contain: layout paint/)
    expect(shellCss).toMatch(/\.session-seam \{[^}]*background: var\(--theme-main-background\)/)
  })

  it('相向的两条描边与内圆角被去掉（否则填了缝也是两条平行线）', () => {
    expect(shellCss).toMatch(/\.workspace-shell\.left-open \.drawer-left \{[^}]*border-right-width: 0/)
    expect(shellCss).toMatch(/\.workspace-shell\.left-open \.workspace-main \{[^}]*border-left-width: 0/)
    expect(shellCss).toMatch(/\.workspace-shell\.left-open \.drawer-left \{[^}]*border-top-right-radius: 0/)
    expect(shellCss).toMatch(/\.workspace-shell\.left-open \.workspace-main \{[^}]*border-top-left-radius: 0/)
  })

  it('连接层仍在，且伸入量与内凹圆角都走令牌', () => {
    expect(shellCss).toMatch(/\.session-fusion \{[^}]*pointer-events: none/)
    // user:“标签出去了…高亮块右侧伸出了侧栏边界，在侧栏与主区之间露出一截突兀的深色方块”+
    // (连接层原来往内容区伸 12px，自身又画一块深色，就成了悬在缝里的那块；伸入量归零，
    //  跨缝的连续感改由「行填充顶到侧栏内缘 + 缝同色」承担)。
    expect(shellCss).toContain('--session-fusion-inset: 0px')
    expect(shellCss).toContain('--session-fusion-radius: var(--radius)')
  })
})

// user:“给定主区 655px + 分屏 430px，输入栏右缘必须 < 分屏左缘；再给一组「主内容=浏览器」的用例”+
// (这两组是截图里的真实分屏：只要输入栏还靠 CSS 级联的变量命中，缺一个变量就回退 100vw；
//  这里改成把实测几何直接写成内联样式，纯函数先把它算死，跑起来就不可能再越界。)
describe('输入栏内联几何：直接落在主列里', () => {
  it('主区 655 + 分屏 430：右缘在主列内，且严格小于分屏左缘', () => {
    const region: Box = { x: 385, y: 36, width: 655, height: 700 }
    const aux: Box = { x: 1040, y: 36, width: 430, height: 700 }
    const style = composerColumnStyle(region)
    const left = Number.parseFloat(style.left)
    const width = Number.parseFloat(style.width)
    const maxWidth = Number.parseFloat(style.maxWidth)
    // 内联给的是中心线，配合 CSS 的 translateX(-50%)：右缘 = 中心 + 宽/2。
    expect(width).toBeLessThanOrEqual(maxWidth)
    expect(left + width / 2).toBeLessThan(aux.x)
    expect(left - width / 2).toBeGreaterThanOrEqual(region.x)
  })

  it('主内容＝浏览器：主列就是浏览器那一格，输入栏只落在它里面', () => {
    const browserColumn: Box = { x: 0, y: 36, width: 900, height: 700 }
    const aux: Box = { x: 900, y: 36, width: 540, height: 700 }
    const style = composerColumnStyle(browserColumn)
    const right = Number.parseFloat(style.left) + Number.parseFloat(style.width) / 2
    const left = Number.parseFloat(style.left) - Number.parseFloat(style.width) / 2
    expect(right).toBeLessThan(aux.x)
    expect(left).toBeGreaterThanOrEqual(browserColumn.x)
  })

  it('宽度绝不大于主列：极窄列也只收到列内，不靠 100vw', () => {
    const narrow: Box = { x: 320, y: 0, width: 200, height: 400 }
    const style = composerColumnStyle(narrow)
    expect(Number.parseFloat(style.width)).toBeLessThanOrEqual(200)
    expect(Number.parseFloat(style.width)).toBeLessThanOrEqual(Number.parseFloat(style.maxWidth))
  })
})

// user:“若主列几何变量缺失，就回退到主区容器的 getBoundingClientRect() 而不是 100vw”+
// (上一轮只写 CSS 变量，要连续命中 `.workspace-shell--split` 与继承两跳；这里锁住新路径：
//  实测矩形 → 内联 left/width/max-width → 非分屏时撤掉。)
describe('输入栏内联几何：写入与撤销（源码锁）', () => {
  const composable = read('../src/composables/useComposerColumn.ts')

  it('把实测列几何写成内联样式，而不是只写变量', () => {
    expect(composable).toContain("setProperty('left'")
    expect(composable).toContain("setProperty('width'")
    expect(composable).toContain("setProperty('max-width'")
    expect(composable).toContain('getBoundingClientRect()')
  })

  it('只有在分屏形态才夹：不在分屏时把内联值撤掉，交还给 CSS', () => {
    expect(composable).toContain('workspace-shell--split')
    expect(composable).toContain('removeProperty')
  })
})
