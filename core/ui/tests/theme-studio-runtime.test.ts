import { describe, expect, it } from 'vitest'
import { createEmptyStudioDocument } from '../src/themeStudio/schema.ts'
import { applyStudioDocument, STUDIO_STYLE_ID } from '../src/themeStudio/runtime.ts'

/**
 * user:“运行时：读取保存好的主题配置，不加载完整编辑器”+
 * (坏文档不写样式；重复应用只保留一个节点；卸载后样式彻底移除。)
 */
const base = () => createEmptyStudioDocument('custom', new Date('2026-10-29T00:00:00.000Z'))

describe('主题运行时注入', () => {
  it('合法文档写入一个样式节点', () => {
    const container = document.createElement('div')
    const document_ = base()
    document_.nodes['shell.sidebar'] = { spacing: { gap: 6 } }

    const result = applyStudioDocument(document_, { container })
    expect(result.ok).toBe(true)
    const style = container.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_STYLE_ID}"]`)
    expect(style).toBeTruthy()
    expect(style!.textContent).toContain('gap: 6px')

    if (result.ok) result.dispose()
    expect(container.querySelector('style')).toBeNull()
  })

  it('重复应用复用同一个节点并替换内容', () => {
    const container = document.createElement('div')
    const first = base()
    first.nodes['shell.sidebar'] = { spacing: { gap: 4 } }
    const second = base()
    second.nodes['shell.sidebar'] = { spacing: { gap: 10 } }

    const a = applyStudioDocument(first, { container })
    const b = applyStudioDocument(second, { container })
    expect(a.ok && b.ok).toBe(true)
    const styles = container.querySelectorAll('style')
    expect(styles).toHaveLength(1)
    expect(styles[0].textContent).toContain('gap: 10px')
    expect(styles[0].textContent).not.toContain('gap: 4px')

    if (b.ok) b.dispose()
  })

  it('非法文档一条样式都不写', () => {
    const container = document.createElement('div')
    const broken = base()
    broken.nodes['not.registered'] = { color: '#ffffff' }

    const result = applyStudioDocument(broken, { container })
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.errors.length).toBeGreaterThan(0)
    expect(container.querySelector('style')).toBeNull()
  })
})
