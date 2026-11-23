import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

/**
 * user:“不再留拖拽的空位，而是非交互区域均可拖拽”+
 * “上方的所有标题文字无法被左键拖动选中，会话标题需要先点击进入编辑才是正常文本”+
 * (标题带上按下左键就拖窗；按钮、输入框、标签页等交互件除外——拖窗既不会误触控件，
 *  也不会顺手把标题文字拖成选区。标题文字本身在显示态不参与选择，点击才进入编辑)。
 */
const INTERACTIVE_SELECTOR = [
  'button',
  'a',
  'input',
  'textarea',
  'select',
  'summary',
  'label',
  '[role="tab"]',
  '[role="button"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[contenteditable="true"]',
  '[data-no-window-drag]',
].join(',')

/** 仅由标题带的空白区域调用：命中交互件就交还给控件自己处理。 */
export function startWindowDragFromBlank(event: PointerEvent): void {
  if (event.button !== 0 || !isTauri()) return
  const target = event.target
  if (!(target instanceof Element)) return
  if (target.closest(INTERACTIVE_SELECTOR)) return
  // 拖窗时不要顺带选中标题文字。
  event.preventDefault()
  try {
    void Promise.resolve(getCurrentWindow().startDragging()).catch(() => undefined)
  } catch {
    // 展厅/纯浏览器预览里没有真实窗口，静默跳过。
  }
}
