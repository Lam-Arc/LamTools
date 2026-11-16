// user:“确保视觉、功能和交互不退化”+(模态对话框的 Tab 在可用控件之间循环，不让键盘焦点落到遮罩后的页面)。
export function trapDialogTab(event: KeyboardEvent): void {
  const dialog = event.currentTarget
  if (!(dialog instanceof HTMLElement)) return
  const targets = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])'))
    .filter(element => !element.matches(':disabled') && !element.closest('[inert], [aria-hidden="true"]') && element.tabIndex >= 0 && element.getClientRects().length > 0 && getComputedStyle(element).visibility === 'visible')
  if (!targets.length) { event.preventDefault(); return }
  const first = targets[0]
  const last = targets[targets.length - 1]
  const current = document.activeElement
  const currentIsTarget = targets.some(target => target === current)
  if (event.shiftKey && (current === first || !currentIsTarget)) {
    event.preventDefault(); last.focus()
  } else if (!event.shiftKey && (current === last || !currentIsTarget)) {
    event.preventDefault(); first.focus()
  }
}
