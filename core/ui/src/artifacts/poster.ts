/**
 * 视频封面：把一段视频的首帧画成一张静态图。
 *
 * 浏览器没有"读视频某一帧"的直接接口，所以借一个不挂进文档的 <video> 元素解码、
 * 用 canvas 取一帧、编成 JPEG 的 data URL。0 秒处常常是黑场，因此默认退一点点
 * （0.1 秒）取真正有画面的那一帧。全程有超时兜底：拿不到帧就返回 null，
 * 界面退回自绘封面，绝不让一面墙停在这里等。
 */

export interface VideoPosterOptions {
  /** 取帧位置（秒）。0 秒处常见黑场，所以默认在它之后一点点。 */
  atSeconds?: number
  /** 输出图的最大宽度，超过就等比缩小。 */
  maxWidth?: number
  /** JPEG 质量。 */
  quality?: number
  /** 整体超时；到点即放弃。 */
  timeoutMs?: number
}

export function extractVideoPoster(source: string, options: VideoPosterOptions = {}): Promise<string | null> {
  if (typeof document === 'undefined') return Promise.resolve(null)
  const atSeconds = options.atSeconds ?? 0.1
  const maxWidth = options.maxWidth ?? 480
  const quality = options.quality ?? 0.72
  const timeoutMs = options.timeoutMs ?? 8_000

  return new Promise((resolve) => {
    const video = document.createElement('video')
    let settled = false
    const finish = (poster: string | null): void => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      video.removeAttribute('src')
      video.load() // 让浏览器把解码器收回去
      resolve(poster)
    }
    const timer = window.setTimeout(() => finish(null), timeoutMs)
    video.muted = true
    video.playsInline = true
    video.preload = 'auto'
    video.addEventListener('error', () => finish(null), { once: true })
    video.addEventListener('loadeddata', () => {
      const duration = video.duration
      const target = Number.isFinite(duration) && duration > atSeconds ? atSeconds : 0
      if (target <= 0) {
        finish(drawFrame(video, maxWidth, quality))
        return
      }
      video.addEventListener('seeked', () => finish(drawFrame(video, maxWidth, quality)), { once: true })
      try {
        video.currentTime = target
      } catch {
        finish(drawFrame(video, maxWidth, quality))
      }
    }, { once: true })
    video.src = source
  })
}

function drawFrame(video: HTMLVideoElement, maxWidth: number, quality: number): string | null {
  const width = video.videoWidth
  const height = video.videoHeight
  if (!width || !height) return null
  const scale = Math.min(1, maxWidth / width)
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(width * scale))
  canvas.height = Math.max(1, Math.round(height * scale))
  const context = canvas.getContext('2d')
  if (!context) return null
  context.drawImage(video, 0, 0, canvas.width, canvas.height)
  try {
    return canvas.toDataURL('image/jpeg', quality)
  } catch {
    // 画布被跨源字节污染时取不到图：退回自绘封面。
    return null
  }
}
