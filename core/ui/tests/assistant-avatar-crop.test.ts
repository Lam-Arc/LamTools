import { describe, expect, it } from 'vitest'

import {
  ASSISTANT_AVATAR_EXPORT_SIZE,
  avatarCoverScale,
  avatarCropSourceRect,
  avatarDisplaySize,
  centeredAvatarOffset,
  clampAvatarOffset,
  rescaleAvatarOffset,
} from '../src/helpers/assistantAvatarCrop'

/**
 * user:“助手头像那块别填链接 上传，裁切”+(裁切框固定正方形，图片按 cover 铺满；
 * 这组测试锁住“框里看到什么就导出什么”的几何换算)
 */
describe('assistant avatar crop geometry', () => {
  const frame = 200

  it('covers the square frame and centers a wide image', () => {
    const image = { width: 800, height: 400 }
    expect(avatarCoverScale(frame, image)).toBe(0.5)
    const display = avatarDisplaySize(frame, image, 1)
    expect(display).toEqual({ width: 400, height: 200 })
    expect(centeredAvatarOffset(frame, display)).toEqual({ x: -100, y: 0 })
  })

  it('never lets a drag expose empty space around the image', () => {
    const display = { width: 400, height: 200 }
    expect(clampAvatarOffset({ x: 80, y: 80 }, frame, display)).toEqual({ x: 0, y: 0 })
    expect(clampAvatarOffset({ x: -9999, y: -9999 }, frame, display)).toEqual({ x: -200, y: 0 })
  })

  it('keeps the frame center anchored while zooming', () => {
    const image = { width: 800, height: 400 }
    const before = avatarDisplaySize(frame, image, 1)
    const offset = centeredAvatarOffset(frame, before)
    const after = avatarDisplaySize(frame, image, 2)
    const next = rescaleAvatarOffset(frame, before, after, offset)

    // 放大后仍以图片中心为取景中心：左右各留一半溢出。
    expect(next).toEqual({ x: (frame - after.width) / 2, y: (frame - after.height) / 2 })
  })

  it('maps the visible square back to source pixels', () => {
    const image = { width: 800, height: 400 }
    const display = avatarDisplaySize(frame, image, 1)
    const offset = centeredAvatarOffset(frame, display)
    expect(avatarCropSourceRect(frame, image, 1, offset)).toEqual({
      sx: 200,
      sy: 0,
      width: 400,
      height: 400,
    })
  })

  it('clamps the source rect inside the image even for out-of-range offsets', () => {
    const image = { width: 600, height: 900 }
    const rect = avatarCropSourceRect(frame, image, 4, { x: 9999, y: -9999 })
    expect(rect.sx).toBeGreaterThanOrEqual(0)
    expect(rect.sy).toBeGreaterThanOrEqual(0)
    expect(rect.sx + rect.width).toBeLessThanOrEqual(image.width)
    expect(rect.sy + rect.height).toBeLessThanOrEqual(image.height)
    expect(rect.width).toBe(rect.height)
  })

  it('exports a square canvas large enough for the avatar', () => {
    expect(ASSISTANT_AVATAR_EXPORT_SIZE).toBeGreaterThanOrEqual(128)
  })
})
