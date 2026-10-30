import { beforeEach, describe, expect, it } from 'vitest'
import { applyStoredPublishedTheme } from '../src/themeStudio/bootstrap.ts'
import { STUDIO_STYLE_ID } from '../src/themeStudio/runtime.ts'
import { createEmptyStudioDocument, type StudioDocument } from '../src/themeStudio/schema.ts'
import { THEME_STUDIO_STORAGE_KEY } from '../src/themeStudio/constants.ts'

/**
 * user:“而且为什么这个点了发布之后 它的修改不生效啊”+
 * (发布过的主题是长期生效的：应用启动时就要把已发布文档恢复为正式样式，
 *  而不是只在编辑器打开期间可见。)
 */
const styleCount = () => document.head.querySelectorAll(`style[data-ui-theme-studio="${STUDIO_STYLE_ID}"]`).length
const styleText = () => document.head.querySelector(`style[data-ui-theme-studio="${STUDIO_STYLE_ID}"]`)?.textContent || ''

function publishedDocument(): StudioDocument {
  const document = createEmptyStudioDocument('studio')
  document.nodes['shell.sidebar'] = { spacing: { gap: 8 } }
  return document
}

describe('启动恢复已发布主题', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  it('本地存储里有已发布文档时，启动即应用为正式样式', () => {
    localStorage.setItem(THEME_STUDIO_STORAGE_KEY, JSON.stringify(publishedDocument()))

    expect(applyStoredPublishedTheme()).toBe(true)
    expect(styleCount()).toBe(1)
    expect(styleText()).toContain('gap: 8px')
  })

  it('没有存储文档时不创建样式节点', () => {
    expect(applyStoredPublishedTheme()).toBe(false)
    expect(styleCount()).toBe(0)
  })

  it('坏文档拒绝应用，界面保持默认外观', () => {
    localStorage.setItem(THEME_STUDIO_STORAGE_KEY, JSON.stringify({ schemaVersion: 99 }))

    expect(applyStoredPublishedTheme()).toBe(false)
    expect(styleCount()).toBe(0)
  })

  it('文档内嵌素材按素材表解析为地址', () => {
    const document = publishedDocument()
    document.assets.push({
      id: 'asset-abc123',
      sha256: 'a'.repeat(64),
      mime: 'image/png',
      width: 4,
      height: 4,
      url: 'data:image/png;base64,QQ==',
    })
    document.nodes['shell.sidebar'] = { background: { type: 'asset', assetRef: 'asset-abc123', fit: 'cover', overflow: 'clipped' } }
    localStorage.setItem(THEME_STUDIO_STORAGE_KEY, JSON.stringify(document))

    expect(applyStoredPublishedTheme()).toBe(true)
    expect(styleText()).toContain('--ui-asset-asset-abc123: url("data:image/png;base64,QQ==")')
  })

  // user:“把布局规则变量给统一”+(布局变量随发布落到 :root，重启后整条布局链保持)
  it('布局变量编译到 :root，非法变量名与数值被拒绝', () => {
    const doc = publishedDocument()
    doc.variables = { '--layout-sidebar-width': '320px' } as never
    localStorage.setItem(THEME_STUDIO_STORAGE_KEY, JSON.stringify(doc))

    expect(applyStoredPublishedTheme()).toBe(true)
    expect(styleText()).toContain(':root { --layout-sidebar-width: 320px }')

    globalThis.document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
    doc.variables = { '--evil': '320px' } as never
    localStorage.setItem(THEME_STUDIO_STORAGE_KEY, JSON.stringify(doc))
    expect(applyStoredPublishedTheme()).toBe(false)

    doc.variables = { '--layout-sidebar-width': 'url(javascript:1)' } as never
    localStorage.setItem(THEME_STUDIO_STORAGE_KEY, JSON.stringify(doc))
    expect(applyStoredPublishedTheme()).toBe(false)
  })
})
