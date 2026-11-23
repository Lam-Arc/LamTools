/**
 * 把图片放进系统剪贴板。
 *
 * user:“提供复制/外部打开键”+(复制就是“拿走这张图去别处粘贴”，所以落到系统剪贴板：
 *  有标注就是标注后的合成图，没标注就是原图)。
 *
 * 两层实现：优先 Clipboard API（Chromium 支持写 image/png），失败时退回
 * 「选中一个隐藏的 img 再 execCommand('copy')」这条老路——WebView 在少数环境里
 * 会拒绝 ClipboardItem，但选区复制仍然可用。
 */

/** 光有扩展名不够：剪贴板只保证认识 PNG，所以统一转成 PNG 再写。 */
async function toPngBlob(blob: Blob): Promise<Blob> {
  if (blob.type === 'image/png') return blob
  const url = URL.createObjectURL(blob)
  try {
    const image = new Image()
    image.src = url
    await image.decode().catch(() => undefined)
    if (!image.naturalWidth || !image.naturalHeight) throw new Error('图片无法解码')
    const canvas = document.createElement('canvas')
    canvas.width = image.naturalWidth
    canvas.height = image.naturalHeight
    const context = canvas.getContext('2d')
    if (!context) throw new Error('图片无法复制')
    context.drawImage(image, 0, 0)
    const png = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/png'))
    if (!png) throw new Error('图片无法复制')
    return png
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** 兜底：选中隐藏的 img，用旧的复制命令把图放进剪贴板。 */
async function copyBySelection(blob: Blob): Promise<void> {
  const url = URL.createObjectURL(blob)
  const image = document.createElement('img')
  image.src = url
  image.alt = ''
  image.style.cssText = 'position:fixed;left:-9999px;top:0;width:1px;height:1px;opacity:0'
  document.body.appendChild(image)
  const selection = typeof window.getSelection === 'function' ? window.getSelection() : null
  try {
    await image.decode().catch(() => undefined)
    const range = document.createRange()
    range.selectNode(image)
    selection?.removeAllRanges()
    selection?.addRange(range)
    if (!document.execCommand('copy')) throw new Error('系统拒绝了这次复制')
  } finally {
    selection?.removeAllRanges()
    image.remove()
    URL.revokeObjectURL(url)
  }
}

export async function copyImageBlob(blob: Blob): Promise<void> {
  const png = await toPngBlob(blob)
  if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
    try {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })])
      return
    } catch { /* 退回选区复制 */ }
  }
  try {
    await copyBySelection(png)
  } catch {
    throw new Error('复制没成功：可以先用「外部打开」再复制')
  }
}
