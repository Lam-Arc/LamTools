import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(__dirname, '../src/styles/split-workspace.css'), 'utf8')

/** 取某条基础规则的规则体（从 `选择器 {` 到下一个 `}`），够用即可。 */
function block(selector: string): string {
  const start = css.indexOf(`${selector} {`)
  if (start < 0) return ''
  const end = css.indexOf('}', start)
  return css.slice(start, end)
}

// user:“Chrome 式标签层级不对，太高了，高于主区了”+
// (层级只有三层：内容与标签同属第 0 层（标签靠 DOM 顺序在内容之前，绝不覆盖内容）；
//  主区 --z-main-surface 高于所有 pane；只有交互指示层才抬到 --z-stage/--z-composer，且只在交互期间挂载)。
describe('分屏层级：标签不高于内容与主区', () => {
  it('pane 框、标签栏、内容层都在第 0 层', () => {
    expect(css).toContain('.split-pane-bar { z-index: 0; }')
    expect(css).toContain('.split-pane-frame,')
    expect(css).toContain('.split-tab-content,')
  })

  it('主区卡片高于 pane 与标签栏', () => {
    expect(block('.split-main-slot')).toContain('z-index: var(--z-main-surface')
    expect(block('.split-pane-bar')).toContain('z-index: 0;')
  })

  it('交互装饰才抬高（插入线 / 拖拽预览 / 分隔条）', () => {
    expect(block('.split-divider')).toContain('z-index: var(--z-stage')
    expect(block('.split-split-preview')).toContain('z-index: var(--z-composer')
    expect(block('.split-split-preview')).toContain('pointer-events: none')
    expect(block('.split-drag-overlay')).toContain('pointer-events: auto')
  })
})

// user:“标签太高、压在主区上”+(光把 z-index 归零不够：transform/filter/opacity<1 会造出新的层叠上下文，
//  那样 z-index:0 的元素照样画在别的层之上。标签这一层不允许自带层叠上下文)。
describe('标签层不许自带层叠上下文', () => {
  for (const selector of ['.split-pane-bar', '.split-pane-tabs']) {
    it(`${selector} 上没有 transform / filter / opacity<1`, () => {
      const rule = block(selector)
      expect(rule.length).toBeGreaterThan(0)
      expect(rule).not.toContain('transform:')
      expect(rule).not.toContain('filter:')
      expect(rule).not.toContain('opacity:')
      expect(rule).not.toContain('will-change')
      expect(rule).not.toContain('isolation')
    })
  }
})
