import { describe, expect, it } from 'vitest'
import {
  THEME_STUDIO_SCHEMA_VERSION,
  createEmptyStudioDocument,
  migrateStudioDocument,
  validateStudioDocument,
} from '../src/themeStudio/index.ts'

/**
 * user:“主题保存、导入导出与恢复机制”+
 * (文档模型是编辑器与运行端的共同契约：非法元素、越权字段、失效素材必须在发布前拦住。)
 */
const empty = () => createEmptyStudioDocument('custom', new Date('2026-10-29T00:00:00.000Z'))

describe('主题文档校验', () => {
  it('空文档合法', () => {
    expect(validateStudioDocument(empty())).toEqual({ ok: true, errors: [], warnings: [] })
  })

  it('未登记的元素被拒绝', () => {
    const document = empty()
    document.nodes['not.registered'] = { color: '#ffffff' }
    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.message.includes('元素未登记'))).toBe(true)
  })

  it('受保护元素不能覆盖样式', () => {
    const document = empty()
    document.nodes['shell.root'] = { color: '#ffffff' }
    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.path === 'nodes.shell.root')).toBe(true)
  })

  it('尺寸与层级已全面开放，未登记属性仍被拒绝（如隐藏）', () => {
    // user:“除了桌面壳”+(除壳之外全部可拖动/可调尺寸/可设层级；未登记属性仍严格拒绝)
    const document = empty()
    document.nodes['shell.main'] = { size: { width: { mode: 'fill' } }, layer: 350, visibility: false }
    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.message.includes('不允许修改 visibility'))).toBe(true)
    expect(result.errors.some((issue) => issue.message.includes('不允许修改 size'))).toBe(false)
    expect(result.errors.some((issue) => issue.message.includes('不允许修改 layer'))).toBe(false)
  })

  // user:“子容器应当是相对于父容器的某一个边或者某几个边，设定距离，而兜底就是距离不得小于 0”+
  // (方案 §4.4/§4.6：单轴最多一个锚点、距离非负、同级锚点必须同父且不允许成环)
  it('锚点校验：负距离、同轴重复与环形依赖都会被拒绝', () => {
    const negative = empty()
    negative.nodes['shell.sidebar'] = { anchors: [{ target: 'parent', edge: 'left', offset: -4 }] }
    const negativeResult = validateStudioDocument(negative)
    expect(negativeResult.ok).toBe(false)
    expect(negativeResult.errors.some((issue) => issue.message.includes('0 到 4000'))).toBe(true)

    const duplicateAxis = empty()
    duplicateAxis.nodes['shell.sidebar'] = {
      anchors: [
        { target: 'parent', edge: 'left', offset: 0 },
        { target: 'parent', edge: 'right', offset: 0 },
      ],
    }
    const duplicateResult = validateStudioDocument(duplicateAxis)
    expect(duplicateResult.ok).toBe(false)
    expect(duplicateResult.errors.some((issue) => issue.message.includes('同一轴只能有一个锚点'))).toBe(true)

    const cyclic = empty()
    cyclic.nodes['shell.titlebar'] = { anchors: [{ target: 'sibling', siblingId: 'shell.app-rail', edge: 'left', offset: 0 }] }
    cyclic.nodes['shell.app-rail'] = { anchors: [{ target: 'sibling', siblingId: 'shell.titlebar', edge: 'left', offset: 0 }] }
    const cyclicResult = validateStudioDocument(cyclic)
    expect(cyclicResult.ok).toBe(false)
    expect(cyclicResult.errors.some((issue) => issue.message.includes('环形依赖'))).toBe(true)
  })

  it('素材背景必须引用已登记素材', () => {
    const document = empty()
    document.nodes['shell.sidebar'] = { background: { type: 'asset', assetRef: 'missing' } }
    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.message.includes('素材未登记'))).toBe(true)
  })

  it('素材标识重复与摘要格式错误都会被拒绝', () => {
    const document = empty()
    document.assets = [
      { id: 'bg', sha256: 'a'.repeat(64), mime: 'image/png', width: 32, height: 64 },
      { id: 'bg', sha256: 'bad', mime: 'image/png', width: 32, height: 64 },
    ]
    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.message.includes('素材标识重复'))).toBe(true)
    expect(result.errors.some((issue) => issue.message.includes('64 位十六进制'))).toBe(true)
  })

  it('素材地址必须是图片 data URL，且有大小上限', () => {
    const document = empty()
    document.assets = [
      { id: 'ok', sha256: 'a'.repeat(64), mime: 'image/png', width: 32, height: 64, url: 'data:image/png;base64,AAAA' },
      { id: 'bad', sha256: 'b'.repeat(64), mime: 'image/png', width: 32, height: 64, url: 'https://example.com/a.png' },
      { id: 'huge', sha256: 'c'.repeat(64), mime: 'image/png', width: 32, height: 64, url: `data:image/png;base64,${'A'.repeat(2_000_001)}` },
    ]
    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.path === 'assets[1].url')).toBe(true)
    expect(result.errors.some((issue) => issue.message.includes('素材过大'))).toBe(true)
  })

  it('颜色、透明度与断点区间都要检查', () => {
    const document = empty()
    document.nodes['shell.sidebar'] = { color: 'red', opacity: 1.4 }
    document.breakpoints = [{ id: 'narrow', minWidth: 900, maxWidth: 600, nodes: {} }]
    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.path === 'nodes.shell.sidebar.color')).toBe(true)
    expect(result.errors.some((issue) => issue.path === 'nodes.shell.sidebar.opacity')).toBe(true)
    expect(result.errors.some((issue) => issue.message.includes('最小宽度不能大于最大宽度'))).toBe(true)
  })

  it('合法覆盖能通过', () => {
    const document = empty()
    document.nodes['shell.sidebar'] = {
      spacing: { gap: 6, padding: [8, 8, 8, 8] },
      radius: 8,
      color: '#f2efeb',
      background: { type: 'solid', color: '#242424', opacity: 0.9 },
      opacity: 0.95,
    }
    document.breakpoints = [{ id: 'narrow', maxWidth: 720, nodes: { 'shell.sidebar': { spacing: { gap: 2 } } } }]
    const result = validateStudioDocument(document)
    expect(result).toEqual({ ok: true, errors: [], warnings: [] })
  })

  it('非对象与版本不支持直接失败', () => {
    expect(validateStudioDocument(null).ok).toBe(false)
    const wrong = { ...empty(), schemaVersion: 99 }
    expect(validateStudioDocument(wrong).ok).toBe(false)
  })
})

describe('主题文档迁移', () => {
  it('没有版本字段的旧文档补齐到当前版本', () => {
    const result = migrateStudioDocument({ themeId: 'legacy', nodes: {} })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.from).toBe(0)
    expect(result.migrated).toBe(true)
    expect(result.document.schemaVersion).toBe(THEME_STUDIO_SCHEMA_VERSION)
    expect(result.document.assets).toEqual([])
    expect(validateStudioDocument(result.document).ok).toBe(true)
  })

  it('当前版本文档不再迁移', () => {
    const result = migrateStudioDocument(empty())
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.migrated).toBe(false)
  })

  it('未来版本拒绝降级并保留原文', () => {
    const raw = { schemaVersion: THEME_STUDIO_SCHEMA_VERSION + 1, themeId: 'future' }
    const result = migrateStudioDocument(raw)
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.raw).toBe(raw)
    expect(result.error).toContain('高于当前支持')
  })
})
