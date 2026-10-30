import { describe, expect, it } from 'vitest'
import {
  compileStudioDocument,
  selectorFor,
  type StudioDocument,
} from '../src/themeStudio/index.ts'
import { createEmptyStudioDocument } from '../src/themeStudio/schema.ts'

/**
 * user:“可视化主题与布局编辑器”+
 * (编译产物是运行端唯一加载的东西：断言选择器权重、尺寸映射、背景与断点输出。)
 */
const base = (): StudioDocument => createEmptyStudioDocument('custom', new Date('2026-10-29T00:00:00.000Z'))

describe('主题文档编译', () => {
  it('选择器使用双属性，压过作用域样式', () => {
    expect(selectorFor('shell.sidebar')).toBe('[data-ui-id="shell.sidebar"][data-ui-id]')
  })

  it('空文档不产出规则', () => {
    expect(compileStudioDocument(base())).toBe('')
  })

  it('尺寸模式映射成具体声明', () => {
    const document = base()
    document.nodes['shell.sidebar'] = {
      size: {
        width: { mode: 'fill' },
        height: { mode: 'fixed', value: 48, min: 32, max: 64 },
      },
    }
    const css = compileStudioDocument(document)
    expect(css).toContain('width: 100%')
    expect(css).toContain('height: 48px')
    expect(css).toContain('min-height: 32px')
    expect(css).toContain('max-height: 64px')
  })

  it('渐变按位置排序并带角度', () => {
    const document = base()
    document.nodes['shell.sidebar'] = {
      background: {
        type: 'gradient',
        angle: 90,
        stops: [
          { color: '#ffffff', position: 100 },
          { color: '#000000', position: 0 },
        ],
      },
    }
    const css = compileStudioDocument(document)
    expect(css).toContain('linear-gradient(90deg, #000000 0%, #ffffff 100%)')
  })

  it('素材背景输出变量引用，并由宿主提供地址', () => {
    const document = base()
    document.assets = [{ id: 'bg', sha256: 'a'.repeat(64), mime: 'image/png', width: 32, height: 64 }]
    document.nodes['shell.sidebar'] = { background: { type: 'asset', assetRef: 'bg', fit: 'contain' } }
    const css = compileStudioDocument(document, { assetUrl: (id) => (id === 'bg' ? '/assets/bg.png' : null) })
    expect(css).toContain('--ui-asset-bg: url("/assets/bg.png")')
    expect(css).toContain('background-image: var(--ui-asset-bg)')
    expect(css).toContain('background-size: contain')
    expect(css).toContain('background-repeat: no-repeat')
  })

  it('模板覆盖命中所有实例', () => {
    const document = base()
    document.templates = { 'template.conversation': { color: '#123456' } }
    const css = compileStudioDocument(document)
    expect(css).toContain('[data-ui-template="template.conversation"][data-ui-template]')
    expect(css).toContain('color: #123456')
  })

  it('九宫格背景输出边框切片', () => {
    const document = base()
    document.assets = [{ id: 'frame', sha256: 'a'.repeat(64), mime: 'image/png', width: 64, height: 64 }]
    document.nodes['shell.sidebar'] = { background: { type: 'asset', assetRef: 'frame', fit: 'nineSlice', slice: { top: 8, right: 8, bottom: 8, left: 12 } } }
    const css = compileStudioDocument(document)
    expect(css).toContain('border-image-source: var(--ui-asset-frame)')
    expect(css).toContain('border-image-slice: 8 8 8 12 fill')
    expect(css).not.toContain('background-image: var(--ui-asset-frame)')
  })

  it('断点输出为媒体查询包裹', () => {
    const document = base()
    document.breakpoints = [{ id: 'narrow', maxWidth: 720, nodes: { 'shell.sidebar': { spacing: { gap: 2 } } } }]
    const css = compileStudioDocument(document)
    expect(css).toContain('@media (max-width: 720px)')
    expect(css).toContain('gap: 2px')
  })

  it('隐藏与文字、层级通过受控变量表达', () => {
    const document = base()
    document.nodes['shell.sidebar'] = {
      visibility: false,
      layer: 4,
      text: { size: 13, lineHeight: 1.5, align: 'center' },
      border: { width: 1, color: '#333333' },
      radius: [8, 8, 0, 0],
    }
    const css = compileStudioDocument(document)
    expect(css).toContain('display: none')
    // user:“Z-index 从 1~9999 一直分层”+(层级就是真实 z-index；未定位元素补 relative 才生效)
    expect(css).toContain('z-index: 4')
    expect(css).toContain('position: relative')
    expect(css).toContain('font-size: 13px')
    expect(css).toContain('text-align: center')
    expect(css).toContain('border: 1px solid #333333')
    expect(css).toContain('border-radius: 8px 8px 0px 0px')
  })
})
