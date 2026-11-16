import { describe, expect, it } from 'vitest'

import { artifactSourcePath } from '../src/helpers/artifactSource'

/**
 * user:“多媒体图片全部加载失败”+(任何还带着路径的条目都必须解析出一个可读地址；
 * 以前只有 attachment:// 与「有项目 id 的相对路径」两种形态能取到字节，其余全变成空串。)
 */
describe('artifactSourcePath', () => {
  const workRoot = 'E:\\LamTools'

  it('routes an attachment reference to the attachment download endpoint', () => {
    expect(artifactSourcePath({ uri: 'attachment://abc123' }))
      .toBe('/attachments/abc123/download')
  })

  // user:“E:/setuptest/constant/.lam/artifact/attachments/<64hex>/image.png”+(真实落盘路径，
  // 那串 64 位是内容 sha256 而不是附件 id，所以不能改写成 /attachments/<sha>/download，)
  // (否则接口只会返回 404；这类绝对路径交给文件引用通道按原路径读。)
  it('reads an attachment-store absolute path through the reference channel', () => {
    const stored = 'E:/setuptest/constant/.lam/artifact/attachments/f5dfc9f8209874c863ed21e4b3b460eadf15c1f3d2b305eba15ae33bcaaa1b08/image.png'
    expect(artifactSourcePath({ path: stored }))
      .toBe(`/files/read-reference?path=${encodeURIComponent(stored)}`)
    expect(artifactSourcePath({ path: stored }, { projectId: 'p1', workRoot }))
      .toBe(`/files/read-reference?path=${encodeURIComponent(stored)}&work_root=${encodeURIComponent(workRoot)}`)
  })

  it('handles backslash storage paths from the Windows attachment store', () => {
    const stored = 'E:\\data\\.lam\\artifact\\attachments\\abc\\img.png'
    expect(artifactSourcePath({ uri: stored }))
      .toBe(`/files/read-reference?path=${encodeURIComponent(stored)}`)
  })

  it('prefers the registered artifact file when a project and artifact id are known', () => {
    expect(artifactSourcePath({ artifact_id: 'a1', uri: '.lam/artifacts/x.png' }, { projectId: 'p1' }))
      .toBe('/projects/p1/artifacts/a1/file')
  })

  it('keeps the project file route for workspace paths inside a project', () => {
    expect(artifactSourcePath({ uri: 'workspace://.lam/artifacts/x.png' }, { projectId: 'p1' }))
      .toBe('/projects/p1/files/raw?path=.lam%2Fartifacts%2Fx.png')
    expect(artifactSourcePath({ path: 'out/report.png' }, { projectId: 'p1' }))
      .toBe('/projects/p1/files/raw?path=out%2Freport.png')
  })

  it('falls back to the reference reader when there is no project context', () => {
    expect(artifactSourcePath({ uri: '.lam/artifacts/x.png' }, { workRoot }))
      .toBe('/files/read-reference?path=.lam%2Fartifacts%2Fx.png&work_root=E%3A%5CLamTools')
  })

  it('never resolves an existing path to an empty string', () => {
    const shapes = [
      { uri: 'attachment://x' },
      { uri: 'workspace://a.png' },
      { path: 'E:/abs/a.png' },
      { path: 'relative/a.png' },
      { metadata: { path: 'meta/a.png' } },
    ]
    for (const shape of shapes) {
      expect(artifactSourcePath(shape, { workRoot })).not.toBe('')
    }
  })

  it('reads the path from metadata when uri and path are absent', () => {
    expect(artifactSourcePath({ metadata: { path: 'from/meta.png' } }, { workRoot }))
      .toBe('/files/read-reference?path=from%2Fmeta.png&work_root=E%3A%5CLamTools')
  })

  it('returns an empty string only when the artifact carries no path at all', () => {
    expect(artifactSourcePath(null)).toBe('')
    expect(artifactSourcePath({})).toBe('')
    expect(artifactSourcePath({ uri: '   ' })).toBe('')
  })
})
