import { describe, expect, it } from 'vitest'

import { sniffThemeImageMime } from '../src/helpers/themeImage'

function bytes(...values: number[]): ArrayBuffer {
  return new Uint8Array(values).buffer
}

function ascii(text: string): number[] {
  return [...new TextEncoder().encode(text)]
}

describe('主题图片格式识别', () => {
  it('按文件头接受静态图与动图格式', () => {
    expect(sniffThemeImageMime(bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a))).toBe('image/png')
    expect(sniffThemeImageMime(bytes(0xff, 0xd8, 0xff, 0xe0))).toBe('image/jpeg')
    // GIF89a：动图按原样接受，不做重编码。
    expect(sniffThemeImageMime(bytes(...ascii('GIF89a'), 0x00))).toBe('image/gif')
    expect(sniffThemeImageMime(bytes(...ascii('RIFF'), 0x00, 0x00, 0x00, 0x00, ...ascii('WEBP')))).toBe('image/webp')
    expect(sniffThemeImageMime(bytes(0x00, 0x00, 0x00, 0x20, ...ascii('ftypavif')))).toBe('image/avif')
    expect(sniffThemeImageMime(bytes(...ascii('<svg xmlns="http://www.w3.org/2000/svg"></svg>')))).toBe('image/svg+xml')
  })

  it('拒绝无法识别的格式', () => {
    expect(sniffThemeImageMime(bytes(...ascii('not-an-image')))).toBeNull()
  })
})
