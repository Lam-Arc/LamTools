import { describe, expect, it, vi } from 'vitest'
import { resolvePreviewRoute, isTextPath, LOCAL_RENDERER_REASONS, nativeMimeFor } from '../src/preview/route'
import { previewKindFor, splitContentFor } from '../src/split/preview'
import { resolvePreviewDocument, type PreviewResolveTransport } from '../src/preview/resolve'
import { filePreviewTarget } from '../src/preview/target'

// user:“预览的三态解析只有一份…不允许再出现「两套按扩展名分派」”+
// (验收重点不是某个扩展名怎么显示，而是「分屏与灯箱读的是同一张表」：
// 表说 native 就两边都给地址，表说 local 就分屏渲染、灯箱说明去哪儿看，
// 表说 unsupported 就两边显示同一句原因)。
function fakeTransport(): PreviewResolveTransport {
  return {
    url: (path: string) => `http://127.0.0.1:52341/api/core${path}`,
    read: vi.fn(async () => new Uint8Array()),
  }
}

describe('preview route table', () => {
  it.each([
    ['cover.png', 'image', 'image/png'],
    ['clip.mp4', 'video', 'video/mp4'],
    ['sound.mp3', 'audio', 'audio/mpeg'],
    ['manual.pdf', 'pdf', 'application/pdf'],
    ['vector.svg', 'image', 'image/svg+xml'],
  ])('routes %s as native %s', (path, family, mime) => {
    const route = resolvePreviewRoute(path)
    expect(route).toEqual({ kind: 'native', mime, family })
  })

  it.each([
    ['report.docx', 'docx'],
    ['budget.xlsx', 'xlsx'],
    ['macro.xlsm', 'xlsx'],
    ['deck.pptx', 'pptx'],
  ])('routes %s to the local renderer %s', (path, renderer) => {
    expect(resolvePreviewRoute(path)).toEqual({ kind: 'local', renderer })
  })

  it('treats Markdown as its own route so排版 does not fall into plain text', () => {
    expect(resolvePreviewRoute('README.md')).toEqual({ kind: 'markdown' })
    expect(resolvePreviewRoute('guide.markdown')).toEqual({ kind: 'markdown' })
  })

  it.each(['main.rs', 'config.yaml', 'Dockerfile', '.gitignore', 'data.json', 'page.html'])(
    'routes %s as plain text',
    path => {
      expect(resolvePreviewRoute(path)).toEqual({ kind: 'text' })
      expect(isTextPath(path)).toBe(true)
    },
  )

  it.each([
    ['clip.mkv'],
    ['movie.avi'],
    ['archive.zip'],
    ['legacy.doc'],
  ])('explains why %s cannot be shown', path => {
    const route = resolvePreviewRoute(path)
    expect(route.kind).toBe('unsupported')
    if (route.kind !== 'unsupported') return
    expect(route.reason).toContain('默认应用打开')
  })
})

describe('split and lightbox read one table', () => {
  it('gives the split the renderer the same route implies', () => {
    for (const path of ['cover.png', 'clip.mp4', 'sound.mp3', 'manual.pdf', 'report.docx', 'budget.xlsx', 'deck.pptx', 'README.md']) {
      const route = resolvePreviewRoute(path)
      const expected = route.kind === 'native' ? route.family : route.kind === 'local' ? route.renderer : 'markdown'
      expect(previewKindFor(path)).toBe(expected)
    }
  })

  it('keeps text in the editor and everything else in the previewer', () => {
    expect(splitContentFor('main.rs')).toBe('editor')
    expect(splitContentFor('cover.png')).toBe('preview')
    expect(splitContentFor('report.docx')).toBe('preview')
    // 看不了的二进制也要进预览器：那里才有原因与「用默认应用打开」的出口。
    expect(splitContentFor('archive.zip')).toBe('preview')
    expect(splitContentFor('')).toBe('editor')
  })

  it('renders native and text routes with the loopback address', async () => {
    for (const path of ['cover.png', 'notes.txt']) {
      const document_ = await resolvePreviewDocument(filePreviewTarget(path, { workRoot: 'E:/p' }), fakeTransport())
      expect(document_.mode).toBe('native')
      if (document_.mode !== 'native') continue
      const url = new URL(document_.url)
      expect(url.searchParams.get('inline')).toBe('1')
      expect(url.searchParams.get('work_root')).toBe('E:/p')
    }
  })

  it('answers an Office file with the split-preview explanation in the lightbox', async () => {
    // user:“不能看的，给的原因和动作与灯箱一致”+(同一份原因文案，两边都读它)。
    const document_ = await resolvePreviewDocument(filePreviewTarget('report.docx'), fakeTransport())
    expect(document_.mode).toBe('unsupported')
    if (document_.mode !== 'unsupported') return
    expect(document_.reason).toBe(LOCAL_RENDERER_REASONS.docx)
    expect(document_.reason).toContain('分屏')
  })

  it('lets a host with local renderers show office files itself', async () => {
    // user:“除了Office类，别的都把它修好”+(分屏自己有 Office 渲染器；声明后不该被判“看不了”)。
    const document_ = await resolvePreviewDocument(
      filePreviewTarget('report.docx', { workRoot: 'E:/p' }),
      fakeTransport(),
      { localRenderers: true },
    )
    expect(document_.mode).toBe('native')
    if (document_.mode !== 'native') return
    expect(document_.url).toContain('/files/read-reference')
  })

  it('routes a browser-unreadable bitmap through the backend raster channel', async () => {
    // user:“除了Office类，别的都把它修好”+(TIF/TIFF 由后端转 PNG，灯箱里照常能看)。
    const document_ = await resolvePreviewDocument(filePreviewTarget('scan.tif', { workRoot: 'E:/p' }), fakeTransport())
    expect(document_.mode).toBe('native')
    if (document_.mode !== 'native') return
    expect(document_.mime).toBe('image/png')
    expect(document_.url).toContain('/files/preview-image')
    expect(document_.url).toContain('work_root=E%3A%2Fp')
  })

  it('reports the native mime from the table for both surfaces', () => {
    expect(nativeMimeFor('a.png')).toBe('image/png')
    expect(nativeMimeFor('a.pdf')).toBe('application/pdf')
    expect(nativeMimeFor('a.txt')).toBeNull()
    expect(nativeMimeFor('a.docx')).toBeNull()
  })
})
