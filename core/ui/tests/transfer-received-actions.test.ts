import { describe, expect, it } from 'vitest'

import {
  formatTime,
  isAbsolutePath,
  receivedActions,
  receivedMeta,
  receivedPreviewTarget,
  receivedRevealArgs,
  receivedTitle,
} from '../src/transfer/received'

/**
 * user:“接收列表：每条可「预览」（走 core/ui/src/preview/ 的统一链路）与「打开所在文件夹」”+
 * 按钮能不能点、点了会发生什么，都在这一层判定；不能预览时要说清楚为什么。
 */
describe('received item actions', () => {
  it('previews through the unified preview chain', () => {
    const target = receivedPreviewTarget({ path: 'C:/lam/received/2026-01-01/a.md' })
    expect(target.kind).toBe('file')
    expect(target.path).toBe('C:/lam/received/2026-01-01/a.md')
    expect(receivedActions({ path: target.path }).canPreview).toBe(true)
  })

  it('does not offer a preview the lightbox cannot render', () => {
    const docx = receivedActions({ path: 'C:/lam/received/a.docx' })
    expect(docx.canPreview).toBe(false)
    // 本地渲染器只在分屏里排版：原因从 preview/route 那一张表来，不在这里另写一份。
    expect(docx.previewReason).toContain('分屏')
    expect(docx.canReveal).toBe(true)
  })

  it('explains unsupported types instead of hiding the button silently', () => {
    const bin = receivedActions({ path: 'C:/lam/received/setup.exe' })
    expect(bin.canPreview).toBe(false)
    expect(bin.previewReason.length).toBeGreaterThan(0)
  })

  it('refuses to act on a record without a path', () => {
    const none = receivedActions({ path: '   ' })
    expect(none.canPreview).toBe(false)
    expect(none.canReveal).toBe(false)
    expect(none.previewReason).toBe('这条记录没有落盘路径。')
  })

  it('only reveals absolute paths, on either platform', () => {
    expect(isAbsolutePath('C:\\lam\\received\\a.txt')).toBe(true)
    expect(isAbsolutePath('/home/lam/received/a.txt')).toBe(true)
    expect(isAbsolutePath('\\\\server\\share\\a.txt')).toBe(true)
    expect(isAbsolutePath('received/a.txt')).toBe(false)
    expect(isAbsolutePath('')).toBe(false)
    expect(receivedRevealArgs({ path: 'C:/lam/a.txt' })).toEqual({ path: 'C:/lam/a.txt' })
    expect(receivedActions({ path: 'relative/a.txt' }).canReveal).toBe(false)
  })

  it('describes the file with size, sender and time', () => {
    const meta = receivedMeta({ transferId: 'x', path: 'C:/a.txt', name: 'a.txt', size: 2048, peer: '手机', from: '', at: 1735689600 })
    expect(meta).toContain('2.0 KB')
    expect(meta).toContain('来自 手机')
    expect(meta).toContain(formatTime(1735689600))
    // 没有来源时不补一句空话。
    const bare = receivedMeta({ transferId: 'y', path: 'C:/b.txt', name: 'b.txt', size: 0, peer: '', from: '', at: 0 })
    expect(bare).toBe('0 B')
  })

  it('falls back to the path for a title', () => {
    expect(receivedTitle({ name: '', path: 'C:/lam/received/b.txt' })).toBe('b.txt')
    expect(receivedTitle({ name: '名字.txt', path: 'C:/lam/c.txt' })).toBe('名字.txt')
  })
})
