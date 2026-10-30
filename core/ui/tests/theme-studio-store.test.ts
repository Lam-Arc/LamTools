import { describe, expect, it } from 'vitest'
import { createStudioStore, type StudioStorage } from '../src/themeStudio/store.ts'
import { STUDIO_STYLE_ID } from '../src/themeStudio/runtime.ts'

/**
 * user:“未保存草稿不影响运行主题”“主题保存、导入导出与恢复机制”+
 * (草稿改完不生效；发布通过校验才落到界面；坏草稿发布被拒且保留草稿。)
 */
function fakeStorage(initial: unknown = null): StudioStorage & { value: unknown } {
  const box = { value: initial }
  return {
    get value() { return box.value },
    set value(next: unknown) { box.value = next },
    read: () => box.value,
    write: (raw) => { box.value = raw },
  }
}

const container = () => document.createElement('div')
const styleCount = (root: HTMLElement) => root.querySelectorAll(`style[data-ui-theme-studio="${STUDIO_STYLE_ID}"]`).length

describe('主题草稿与发布', () => {
  it('编辑草稿不会改变运行界面', () => {
    const root = container()
    const store = createStudioStore({ applyOptions: { container: root } })
    store.setNode('shell.sidebar', { spacing: { gap: 8 } })

    expect(store.dirty.value).toBe(true)
    expect(styleCount(root)).toBe(0)
    store.dispose()
  })

  it('发布后写入运行样式并持久化', () => {
    const root = container()
    const storage = fakeStorage()
    const store = createStudioStore({ storage, applyOptions: { container: root } })
    store.setNode('shell.sidebar', { spacing: { gap: 8 } })

    expect(store.publish().ok).toBe(true)
    expect(store.dirty.value).toBe(false)
    expect(styleCount(root)).toBe(1)
    expect(root.querySelector('style')!.textContent).toContain('gap: 8px')
    expect(storage.value).toBeTruthy()
    store.dispose()
  })

  it('非法草稿发布被拒，保留草稿且不写运行样式', () => {
    const root = container()
    const storage = fakeStorage()
    const store = createStudioStore({ storage, applyOptions: { container: root } })
    store.setNode('shell.root', { color: '#ffffff' })

    const result = store.publish()
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.errors.length).toBeGreaterThan(0)
    expect(store.dirty.value).toBe(true)
    expect(styleCount(root)).toBe(0)
    expect(storage.value).toBeNull()
    store.dispose()
  })

  it('恢复默认清空覆盖并写回', () => {
    const root = container()
    const storage = fakeStorage()
    const store = createStudioStore({ storage, applyOptions: { container: root } })
    store.setNode('shell.sidebar', { spacing: { gap: 8 } })
    store.publish()

    store.reset()
    expect(store.draft.value.nodes).toEqual({})
    expect(store.published.value.nodes).toEqual({})
    expect(styleCount(root)).toBe(1)
    expect(root.querySelector('style')!.textContent).toBe('')
    expect(storage.value).toBeTruthy()
    store.dispose()
  })

  it('读取旧版本文档会先迁移再应用', () => {
    const root = container()
    const store = createStudioStore({ applyOptions: { container: root } })
    const loaded = store.load({ themeId: 'legacy', nodes: { 'shell.sidebar': { spacing: { gap: 4 } } } })

    expect(loaded).toBe(true)
    expect(store.published.value.schemaVersion).toBe(1)
    expect(styleCount(root)).toBe(1)
    expect(root.querySelector('style')!.textContent).toContain('gap: 4px')
    store.dispose()
  })

  it('模板覆盖发布后对所有实例生效', () => {
    const root = container()
    const store = createStudioStore({ storage: fakeStorage(), applyOptions: { container: root } })
    store.setTemplateNode('template.conversation', { color: '#334455' })
    expect(store.publish().ok).toBe(true)
    const css = root.querySelector('style')!.textContent || ''
    expect(css).toContain('[data-ui-template="template.conversation"][data-ui-template]')
    expect(css).toContain('color: #334455')
    store.dispose()
  })

  it('断点覆盖发布后编译成媒体查询', () => {
    const root = container()
    const storage = fakeStorage()
    const store = createStudioStore({ storage, applyOptions: { container: root } })
    store.addBreakpoint('bp-800', 800)
    store.setBreakpointNode('bp-800', 'shell.sidebar', { spacing: { gap: 2 } })

    expect(store.publish().ok).toBe(true)
    expect(root.querySelector('style')!.textContent).toContain('@media (max-width: 800px)')
    expect(storage.value).toBeTruthy()
    store.dispose()
  })

  it('断点强制预览不带媒体查询', () => {
    const root = container()
    const store = createStudioStore({ applyOptions: { container: root } })
    store.addBreakpoint('bp-800', 800)
    store.setBreakpointNode('bp-800', 'shell.sidebar', { spacing: { gap: 2 } })
    store.previewDocument({
      ...store.draft.value,
      nodes: { 'shell.sidebar': { spacing: { gap: 2 } } },
      breakpoints: [],
    })
    const css = root.querySelector('style[data-ui-theme-studio="ui-theme-studio-preview"]')!.textContent || ''
    expect(css).toContain('gap: 2px')
    expect(css).not.toContain('@media')
    store.dispose()
  })

  it('撤销与重做只作用于草稿', () => {
    const store = createStudioStore()
    store.setNode('shell.sidebar', { spacing: { gap: 4 } })
    store.setNode('shell.sidebar', { spacing: { gap: 8 } })

    expect(store.canUndo.value).toBe(true)
    store.undo()
    expect(store.draft.value.nodes['shell.sidebar'].spacing?.gap).toBe(4)
    store.undo()
    expect(store.draft.value.nodes['shell.sidebar']).toBeUndefined()
    expect(store.canUndo.value).toBe(false)

    store.redo()
    expect(store.draft.value.nodes['shell.sidebar'].spacing?.gap).toBe(4)
    store.dispose()
  })

  it('损坏的文档读取失败并报错', () => {
    const root = container()
    const store = createStudioStore({ applyOptions: { container: root } })
    expect(store.load({ schemaVersion: 99, themeId: 'future' })).toBe(false)
    expect(store.errors.value.length).toBeGreaterThan(0)
    expect(styleCount(root)).toBe(0)
    store.dispose()
  })

  // user:“并加一个编辑模式的开关和一个取消（不保存退出）”+
  // (取消=不保存退出：草稿回滚到已发布版本并清空历史，未发布改动全部丢弃。)
  it('取消草稿会回滚到已发布版本并清历史', () => {
    const root = container()
    const store = createStudioStore({ applyOptions: { container: root } })
    store.setNode('shell.sidebar', { spacing: { gap: 8 } })
    expect(store.dirty.value).toBe(true)

    store.discard()
    expect(store.dirty.value).toBe(false)
    expect(store.draft.value.nodes).toEqual({})
    expect(store.canUndo.value).toBe(false)
    expect(store.canRedo.value).toBe(false)
    store.dispose()
  })

  // user:“而且为什么这个点了发布之后 它的修改不生效啊”+
  // (已发布的主题样式是长期生效的运行面，关闭编辑器不能把它一起拆掉。)
  it('关闭编辑器不移除已发布样式', () => {
    const root = container()
    const storage = fakeStorage()
    const store = createStudioStore({ storage, applyOptions: { container: root } })
    store.setNode('shell.sidebar', { spacing: { gap: 8 } })
    store.publish()

    store.dispose()
    expect(styleCount(root)).toBe(1)
    expect(root.querySelector('style')!.textContent).toContain('gap: 8px')
  })
})
