import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type { StudioDocument, StudioNodeStyle } from './schema.ts'
import { createEmptyStudioDocument } from './schema.ts'
import type { StudioIssue } from './validate.ts'
import { validateStudioDocument } from './validate.ts'
import { migrateStudioDocument } from './migrate.ts'
import { applyStudioDocument, STUDIO_PREVIEW_STYLE_ID, STUDIO_STYLE_ID, type ApplyStudioOptions } from './runtime.ts'

/**
 * 草稿与已发布分离。
 *
 * user:“主题保存、导入导出与恢复机制”“未保存草稿不影响运行主题”+
 * (编辑写草稿并实时预览；草稿不落盘、不替换正式主题。
 *  只有发布通过校验才写正式样式并持久化，失败保留草稿并返回错误。)
 */

export interface StudioStorage {
  read: () => unknown
  write: (raw: unknown) => void
}

export interface StudioStoreOptions {
  themeId?: string
  storage?: StudioStorage
  applyOptions?: ApplyStudioOptions
  /** 关闭实时预览，只在发布时落样式；默认开启。 */
  preview?: boolean
}

export interface StudioStore {
  draft: Ref<StudioDocument>
  published: Ref<StudioDocument>
  dirty: ComputedRef<boolean>
  errors: Ref<StudioIssue[]>
  canUndo: ComputedRef<boolean>
  canRedo: ComputedRef<boolean>
  setNode: (id: string, style: StudioNodeStyle) => void
  /** 写布局几何变量（如 --layout-sidebar-width: 320px），整条布局链一起跟随。 */
  setVariable: (name: string, value: string) => void
  removeVariable: (name: string) => void
  setTemplateNode: (id: string, style: StudioNodeStyle) => void
  setInstanceNode: (key: string, templateId: string, style: StudioNodeStyle) => void
  removeInstanceNode: (key: string) => void
  setBreakpointNode: (breakpointId: string, id: string, style: StudioNodeStyle) => void
  removeBreakpointNode: (breakpointId: string, id: string) => void
  addBreakpoint: (breakpointId: string, maxWidth: number) => void
  removeBreakpoint: (breakpointId: string) => void
  previewDocument: (document: StudioDocument) => StudioIssue[]
  removeNode: (id: string) => void
  replaceDraft: (document: StudioDocument) => void
  preview: () => StudioIssue[]
  clearPreview: () => void
  publish: () => { ok: true } | { ok: false; errors: StudioIssue[] }
  reset: () => void
  /** 取消编辑：草稿回滚到已发布版本并清历史，未发布改动全部丢弃。 */
  discard: () => void
  load: (raw: unknown) => boolean
  undo: () => void
  redo: () => void
  dispose: () => void
}

function cloneDocument(document: StudioDocument): StudioDocument {
  return JSON.parse(JSON.stringify(document)) as StudioDocument
}

export function createStudioStore(options: StudioStoreOptions = {}): StudioStore {
  const themeId = options.themeId ?? 'custom'
  const empty = () => createEmptyStudioDocument(themeId)
  const previewEnabled = options.preview !== false

  const draft = ref<StudioDocument>(empty())
  const published = ref<StudioDocument>(empty())
  const errors = ref<StudioIssue[]>([])
  const past = ref<StudioDocument[]>([])
  const future = ref<StudioDocument[]>([])
  const HISTORY_LIMIT = 50
  const dirty = computed(() => JSON.stringify(draft.value) !== JSON.stringify(published.value))
  const canUndo = computed(() => past.value.length > 0)
  const canRedo = computed(() => future.value.length > 0)

  let disposePreview: (() => void) | null = null

  function apply(document: StudioDocument, styleId: string): { ok: true; dispose: () => void } | { ok: false; errors: StudioIssue[] } {
    return applyStudioDocument(document, { ...options.applyOptions, styleId })
  }

  // user:“而且为什么这个点了发布之后 它的修改不生效啊”+
  // (已发布样式是长期生效的运行面：只替换节点内容，不追踪 dispose，
  //  关闭编辑器时它必须留在界面上；编辑器作用域只有预览通道。)
  function applyPublished(): StudioIssue[] {
    const result = apply(published.value, STUDIO_STYLE_ID)
    if (!result.ok) return result.errors
    return []
  }

  function clearPreview(): void {
    disposePreview?.()
    disposePreview = null
  }

  function preview(): StudioIssue[] {
    if (!previewEnabled) return []
    const validation = validateStudioDocument(draft.value)
    if (!validation.ok) return validation.errors
    clearPreview()
    const result = apply(draft.value, STUDIO_PREVIEW_STYLE_ID)
    if (!result.ok) return result.errors
    disposePreview = result.dispose
    return []
  }

  function beginChange(): void {
    past.value.push(cloneDocument(draft.value))
    if (past.value.length > HISTORY_LIMIT) past.value.shift()
    future.value = []
  }

  function touch(): void {
    draft.value = cloneDocument(draft.value)
    draft.value.updatedAt = new Date().toISOString()
    preview()
  }

  function setNode(id: string, style: StudioNodeStyle): void {
    beginChange()
    draft.value.nodes[id] = style
    touch()
  }

  // user:“把布局规则变量给统一”+(布局尺寸写成变量，主区域/输入栏等派生位置自动重算)
  function setVariable(name: string, value: string): void {
    beginChange()
    if (!draft.value.variables) draft.value.variables = {}
    ;(draft.value.variables as Record<string, string>)[name] = value
    touch()
  }

  function removeVariable(name: string): void {
    if (!draft.value.variables || !(name in draft.value.variables)) return
    beginChange()
    delete (draft.value.variables as Record<string, string>)[name]
    touch()
  }

  function setTemplateNode(id: string, style: StudioNodeStyle): void {
    beginChange()
    if (!draft.value.templates) draft.value.templates = {}
    draft.value.templates[id] = style
    touch()
  }

  function setInstanceNode(key: string, templateId: string, style: StudioNodeStyle): void {
    beginChange()
    if (!draft.value.instances) draft.value.instances = {}
    draft.value.instances[key] = { templateId, style }
    touch()
  }

  // user:“模板之上允许单个实例覆盖”+(清除实例改动只删这一条，不动模板)
  function removeInstanceNode(key: string): void {
    if (!draft.value.instances?.[key]) return
    beginChange()
    delete draft.value.instances[key]
    touch()
  }

  function removeBreakpointNode(breakpointId: string, id: string): void {
    const breakpoint = draft.value.breakpoints.find((item) => item.id === breakpointId)
    if (!breakpoint || !(id in breakpoint.nodes)) return
    beginChange()
    delete breakpoint.nodes[id]
    touch()
  }

  function setBreakpointNode(breakpointId: string, id: string, style: StudioNodeStyle): void {
    const breakpoint = draft.value.breakpoints.find((item) => item.id === breakpointId)
    if (!breakpoint) return
    beginChange()
    breakpoint.nodes[id] = style
    touch()
  }

  function addBreakpoint(breakpointId: string, maxWidth: number): void {
    if (draft.value.breakpoints.some((item) => item.id === breakpointId)) return
    beginChange()
    draft.value.breakpoints.push({ id: breakpointId, maxWidth, nodes: {} })
    draft.value.breakpoints.sort((left, right) => (left.maxWidth ?? 0) - (right.maxWidth ?? 0))
    touch()
  }

  function removeBreakpoint(breakpointId: string): void {
    beginChange()
    draft.value.breakpoints = draft.value.breakpoints.filter((item) => item.id !== breakpointId)
    touch()
  }

  /** 用指定文档刷新预览通道，供断点强制预览使用。 */
  function previewDocument(document: StudioDocument): StudioIssue[] {
    if (!previewEnabled) return []
    const validation = validateStudioDocument(document)
    if (!validation.ok) return validation.errors
    clearPreview()
    const result = apply(document, STUDIO_PREVIEW_STYLE_ID)
    if (!result.ok) return result.errors
    disposePreview = result.dispose
    return []
  }

  function removeNode(id: string): void {
    beginChange()
    delete draft.value.nodes[id]
    touch()
  }

  function replaceDraft(document: StudioDocument): void {
    beginChange()
    draft.value = cloneDocument(document)
    preview()
  }

  function undo(): void {
    const previous = past.value.pop()
    if (!previous) return
    future.value.push(cloneDocument(draft.value))
    draft.value = previous
    preview()
  }

  function redo(): void {
    const next = future.value.pop()
    if (!next) return
    past.value.push(cloneDocument(draft.value))
    draft.value = next
    preview()
  }

  function publish(): { ok: true } | { ok: false; errors: StudioIssue[] } {
    const validation = validateStudioDocument(draft.value)
    if (!validation.ok) {
      errors.value = validation.errors
      return { ok: false, errors: validation.errors }
    }
    published.value = cloneDocument(draft.value)
    const applied = applyPublished()
    if (applied.length > 0) {
      errors.value = applied
      return { ok: false, errors: applied }
    }
    clearPreview()
    errors.value = []
    options.storage?.write(published.value)
    return { ok: true }
  }

  function reset(): void {
    past.value = []
    future.value = []
    draft.value = empty()
    published.value = empty()
    errors.value = []
    clearPreview()
    applyPublished()
    options.storage?.write(published.value)
  }

  // user:“并加一个编辑模式的开关和一个取消（不保存退出）”+
  // (取消=不保存退出：草稿回滚到已发布版本，撤销重做历史一并清空。)
  function discard(): void {
    past.value = []
    future.value = []
    draft.value = cloneDocument(published.value)
    errors.value = []
    clearPreview()
  }

  function load(raw: unknown): boolean {
    const migrated = migrateStudioDocument(raw)
    if (!migrated.ok) {
      errors.value = [{ path: '', message: migrated.error }]
      return false
    }
    const validation = validateStudioDocument(migrated.document)
    if (!validation.ok) {
      errors.value = validation.errors
      return false
    }
    past.value = []
    future.value = []
    draft.value = cloneDocument(migrated.document)
    published.value = cloneDocument(migrated.document)
    errors.value = []
    clearPreview()
    applyPublished()
    return true
  }

  // 启动时先读已发布版本；读不到就用空文档，界面保持默认外观。
  if (options.storage) {
    const raw = options.storage.read()
    if (raw) load(raw)
  }

  return {
    draft,
    published,
    dirty,
    errors,
    canUndo,
    canRedo,
    setNode,
    setVariable,
    removeVariable,
    setTemplateNode,
    setInstanceNode,
    removeInstanceNode,
    setBreakpointNode,
    removeBreakpointNode,
    addBreakpoint,
    removeBreakpoint,
    previewDocument,
    removeNode,
    replaceDraft,
    preview,
    clearPreview,
    publish,
    reset,
    discard,
    load,
    undo,
    redo,
    dispose: () => {
      // 已发布样式不随编辑器卸载（见 applyPublished）；编辑器只负责拆掉预览通道。
      clearPreview()
    },
  }
}
