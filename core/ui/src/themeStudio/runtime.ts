import type { StudioDocument } from './schema.ts'
import type { StudioIssue } from './validate.ts'
import { validateStudioDocument } from './validate.ts'
import { compileStudioDocument, type CompileOptions } from './compile.ts'

/**
 * 运行端注入。
 *
 * user:“运行时：读取保存好的主题配置，不加载完整编辑器”+
 * (文档先校验再编译；坏文档一条样式都不写，运行时保持默认外观。
 *  同一时刻只存在一个覆盖样式节点，更新时替换内容而不是叠加。)
 */

export const STUDIO_STYLE_ID = 'ui-theme-studio-overrides'
/** 编辑器预览通道：与已发布样式分开，退出编辑即移除。 */
export const STUDIO_PREVIEW_STYLE_ID = 'ui-theme-studio-preview'

export interface ApplyStudioOptions extends CompileOptions {
  /** 挂载位置，默认文档 head；测试可传容器。 */
  container?: HTMLElement
  /** 样式节点标识；编辑器预览用独立标识，避免和已发布主题混在一起。 */
  styleId?: string
}

export type ApplyStudioResult =
  | { ok: true; dispose: () => void }
  | { ok: false; errors: StudioIssue[] }

function ensureStyleElement(container: HTMLElement, styleId: string): HTMLStyleElement {
  const existing = container.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${styleId}"]`)
  if (existing) return existing
  const style = document.createElement('style')
  style.dataset.uiThemeStudio = styleId
  container.appendChild(style)
  return style
}

export function applyStudioDocument(studioDocument: StudioDocument, options: ApplyStudioOptions = {}): ApplyStudioResult {
  const validation = validateStudioDocument(studioDocument)
  if (!validation.ok) {
    return { ok: false, errors: validation.errors }
  }

  const container = options.container ?? globalThis.document.head
  const styleId = options.styleId ?? STUDIO_STYLE_ID
  const style = ensureStyleElement(container, styleId)
  style.textContent = compileStudioDocument(studioDocument, options)

  return {
    ok: true,
    dispose: () => {
      style.remove()
    },
  }
}
