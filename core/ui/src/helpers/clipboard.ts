export async function copyText(text: string): Promise<void> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Android WebView can expose this API while denying its permission.
      // The selection-based copy path still works on some of those devices.
    }
  }

  if (typeof document === 'undefined') throw new Error('当前环境不支持复制')
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  let copied = false
  try {
    textarea.select()
    copied = typeof document.execCommand === 'function' && document.execCommand('copy')
  } catch {
    // Report a single copy failure after removing the temporary control.
  } finally {
    textarea.remove()
  }
  if (!copied) throw new Error('复制失败')
}
