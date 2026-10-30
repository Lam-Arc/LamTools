/**
 * 主题区域图片读取。
 *
 * user:“再加一项/图片，执行多类图片包括动图等”+
 * (图片样式要接受常见静态与动图格式：PNG/JPEG/GIF/WebP/AVIF 与 SVG；
 *  动图按原样保留成 data URL，交给 CSS 背景去播放，不做重编码。
 *  格式按文件头识别、不信任后缀；SVG 拒绝脚本。)
 */

export type ThemeImageMime =
  | 'image/png'
  | 'image/jpeg'
  | 'image/gif'
  | 'image/webp'
  | 'image/avif'
  | 'image/svg+xml'

/** 单张图片上限；主题跟随设置一起存进 localStorage，必须留出配额。 */
export const THEME_IMAGE_MAX_BYTES = 1_500_000

export interface ThemeImageFile {
  dataUrl: string
  mime: ThemeImageMime
}

/** 按文件头识别格式（PNG 容器同时覆盖 APNG，动图不会被降级）。 */
export function sniffThemeImageMime(buffer: ArrayBuffer): ThemeImageMime | null {
  const bytes = new Uint8Array(buffer.slice(0, 16))
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return 'image/png'
  if (bytes[0] === 0xff && bytes[1] === 0xd8) return 'image/jpeg'
  if (bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return 'image/gif'
  if (bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 && bytes[8] === 0x57 && bytes[9] === 0x45) return 'image/webp'
  if (bytes[4] === 0x66 && bytes[5] === 0x74 && bytes[6] === 0x79 && bytes[7] === 0x70
    && bytes[8] === 0x61 && bytes[9] === 0x76 && bytes[10] === 0x69
    && (bytes[11] === 0x66 || bytes[11] === 0x73)) return 'image/avif'
  const head = new TextDecoder().decode(buffer.slice(0, 512)).trim().toLowerCase()
  if (head.startsWith('<?xml') || head.startsWith('<svg')) return 'image/svg+xml'
  return null
}

function toDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('图片读取失败'))
    reader.readAsDataURL(file)
  })
}

/** 读取一张主题背景图；失败时抛出可直接展示给用户的中文原因。 */
export async function readThemeImageFile(file: File): Promise<ThemeImageFile> {
  if (file.size > THEME_IMAGE_MAX_BYTES) throw new Error('图片过大，单张不能超过 1.5MB')
  const [dataUrl, buffer] = await Promise.all([toDataUrl(file), file.arrayBuffer()])
  const mime = sniffThemeImageMime(buffer)
  if (!mime) throw new Error('图片格式无法识别')
  if (mime === 'image/svg+xml' && new TextDecoder().decode(buffer).toLowerCase().includes('<script')) {
    throw new Error('SVG 不允许包含脚本')
  }
  return { dataUrl, mime }
}
