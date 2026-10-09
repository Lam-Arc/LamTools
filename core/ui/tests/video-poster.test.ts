import { afterEach, describe, expect, it, vi } from 'vitest'

import { extractVideoPoster } from '../src/artifacts/poster'

/**
 * 视频封面取帧：借 <video> 解码、canvas 画一帧。jsdom 既没有解码器也没有画布，
 * 所以这里换上一对能按剧本发事件的替身，验的是"取帧的时机与收尾"——
 * 什么时候算拿到了帧、拿不到时是否安静地退回 null。
 */

interface FakeVideo {
  duration: number
  videoWidth: number
  videoHeight: number
  currentTime: number
  muted: boolean
  playsInline: boolean
  preload: string
  src: string
  created: boolean
  addEventListener: (type: string, handler: () => void) => void
  removeAttribute: () => void
  load: () => void
  fire: (type: string) => void
}

function stubMedia(options: { duration?: number; width?: number; height?: number } = {}) {
  const listeners: Record<string, Array<() => void>> = {}
  const video: FakeVideo = {
    duration: options.duration ?? 12,
    videoWidth: options.width ?? 1280,
    videoHeight: options.height ?? 720,
    currentTime: 0,
    muted: false,
    playsInline: false,
    preload: '',
    src: '',
    created: false,
    addEventListener: (type, handler) => { (listeners[type] ||= []).push(handler) },
    removeAttribute: () => undefined,
    load: () => undefined,
    fire: (type) => { for (const handler of listeners[type] || []) handler() },
  }
  const drawImage = vi.fn()
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({ drawImage }),
    toDataURL: () => 'data:image/jpeg;base64,frame',
  }
  const original = document.createElement.bind(document)
  const spy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    if (tag === 'video') {
      video.created = true
      return video as unknown as HTMLElement
    }
    if (tag === 'canvas') return canvas as unknown as HTMLElement
    return original(tag)
  })
  return { video, canvas, drawImage, restore: () => spy.mockRestore() }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('extractVideoPoster', () => {
  it('draws a frame a little past zero and hands back a JPEG data URL', async () => {
    const media = stubMedia()

    const pending = extractVideoPoster('blob:clip')
    expect(media.video.src).toBe('blob:clip')
    media.video.fire('loadeddata')
    expect(media.video.currentTime).toBe(0.1)
    media.video.fire('seeked')

    await expect(pending).resolves.toBe('data:image/jpeg;base64,frame')
    // 画到画布上的尺寸按最大宽度缩过，封面不该带着 1280px 的原始尺寸进内存。
    expect(media.canvas.width).toBe(480)
    expect(media.canvas.height).toBe(270)
    expect(media.drawImage).toHaveBeenCalledWith(media.video, 0, 0, 480, 270)
  })

  it('returns null instead of waiting when the bytes cannot be decoded', async () => {
    const media = stubMedia()

    const pending = extractVideoPoster('blob:broken')
    media.video.fire('error')

    await expect(pending).resolves.toBeNull()
  })

  it('gives up on its own when the element never reports a frame', async () => {
    const media = stubMedia()
    vi.useFakeTimers()
    try {
      const pending = extractVideoPoster('blob:slow', { timeoutMs: 1_000 })
      expect(media.video.created).toBe(true)
      await vi.advanceTimersByTimeAsync(1_000)
      await expect(pending).resolves.toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not hand back an empty canvas when the element reports no size', async () => {
    // 时长也为 0 才走"立刻作画"那一条：否则它会等一个不会到来的定位完成。
    const media = stubMedia({ duration: 0, width: 0, height: 0 })

    const pending = extractVideoPoster('blob:audio-only')
    media.video.fire('loadeddata')

    await expect(pending).resolves.toBeNull()
  })
})
