/**
 * 交互层工具条验收：只保留清空，空的时候整条不出现。
 *
 * user:“那个『收起』也去掉”+(工具条里只剩清空一个按钮；没有标记时连空条都不该留在
 *  屏幕上。注释里会引用用户原话，所以断言看的是工具条内的按钮，不是全文里有没有这两个字)。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(__dirname, '../src/overlay/OverlaySurface.vue'), 'utf8')

function toolbarSource(): string {
  const match = source.match(/<div[^>]*class="[^"]*overlay-bar[^"]*"[\s\S]*?<\/div>/)
  return match ? match[0] : ''
}

describe('交互层工具条', () => {
  it('工具条里只有清空一个按钮', () => {
    const bar = toolbarSource()
    expect(bar).not.toBe('')
    expect(bar.match(/<button/g) ?? []).toHaveLength(1)
    expect(bar).toContain('清空')
    expect(bar).not.toContain('收起')
  })

  it('只给它用的关窗函数已经删掉', () => {
    expect(source).not.toContain('closeLayer')
  })

  it('没有标记时工具条整条不渲染', () => {
    const barTag = source.match(/<div[^>]*class="[^"]*overlay-bar[^"]*"[^>]*>/)
    expect(barTag).not.toBeNull()
    expect(barTag![0]).toContain('v-if="marks.length"')
  })

  it('左边有一句状态文字', () => {
    expect(toolbarSource()).toContain('Sunday 标注中')
  })

  it('整屏边框和胶囊共用同一套样式', () => {
    const cu = readFileSync(resolve(__dirname, '../src/components/ComputerUseBar.vue'), 'utf8')
    expect(cu).toContain('hud-screen-frame')
    expect(source).toContain('hud-screen-frame')
    expect(cu).not.toContain('background: conic-gradient(')
    // 旧变量名已经随共用样式删掉，留着会静默失效。
    expect(cu).not.toContain('--cu-bar-angle')
  })

  it('整屏边框收 6px 圆角并填满四个角', () => {
    const pill = readFileSync(resolve(__dirname, '../src/styles/hud-pill.css'), 'utf8')
    expect(pill).toContain('border-radius: 6px')
    expect(pill).toContain('.hud-screen-frame::before')
    // 四个角各 6×6 的填充块，少一个就会露出缺口。
    expect((pill.match(/6px 6px no-repeat/g) ?? []).length).toBeGreaterThanOrEqual(4)
  })

  it('外观和 Computer Use 状态条共用同一份样式', () => {
    const cu = readFileSync(resolve(__dirname, '../src/components/ComputerUseBar.vue'), 'utf8')
    const pill = readFileSync(resolve(__dirname, '../src/styles/hud-pill.css'), 'utf8')
    expect(source).toContain("import '@/styles/hud-pill.css'")
    expect(cu).toContain("import '@/styles/hud-pill.css'")
    expect(source).toContain('hud-pill__ring')
    expect(cu).toContain('hud-pill__ring')
    // 胶囊外观只允许在 hud-pill.css 里定义一次，组件里不许再写一份。
    expect(pill).toContain('.hud-pill {')
    expect(source).not.toContain('backdrop-filter: blur(18px)')
    // 组件里不许再各自写一份胶囊本体。
    expect(cu).not.toContain('.cu-bar {')
  })
})
