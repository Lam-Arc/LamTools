import { describe, expect, it, vi } from 'vitest'
import {
  isDangerousReference,
  isInternalPreviewUrl,
  nativeMimeFor,
  previewMimeLabel,
  resolvePreviewDocument,
  sanitizePreviewHtml,
  type PreviewResolveTransport,
} from '../src/preview/resolve'
import { filePreviewTarget, htmlPreviewTarget, previewTargetKey, previewTargetTitle, urlPreviewTarget } from '../src/preview/target'

// user:“这些是纯函数，先写单测：按扩展名/MIME 分派、workRoot 拼接、危险 scheme 拒绝、
// 未知类型落到 unsupported”+(内容寻址层的验收：三态判定不依赖真实后台)。
function fakeTransport(overrides: Partial<PreviewResolveTransport> = {}): PreviewResolveTransport {
  return {
    url: (path: string) => `http://127.0.0.1:52341/api/core${path}`,
    read: vi.fn(async () => new Uint8Array()),
    ...overrides,
  }
}

describe('preview target', () => {
  it('describes a file target with its scope', () => {
    const target = filePreviewTarget('E:/p/a.png', { workRoot: 'E:/p', projectId: 'proj-1' })
    expect(target).toEqual({ kind: 'file', path: 'E:/p/a.png', workRoot: 'E:/p', projectId: 'proj-1' })
    expect(previewTargetTitle(target)).toBe('a.png')
  })

  it('keys the same file the same way regardless of separators and case', () => {
    // user:“两种形态之间移交同一目标不丢失内容”+(身份必须只看内容本身)。
    const a = previewTargetKey(filePreviewTarget('E:\\p\\A.PNG', { workRoot: 'E:/p' }))
    const b = previewTargetKey(filePreviewTarget('e:/p/a.png', { workRoot: 'e:/p/' }))
    expect(a).toBe(b)
    expect(a).not.toBe(previewTargetKey(filePreviewTarget('E:/q/a.png', { workRoot: 'E:/p' })))
  })

  it('titles a url target by host', () => {
    expect(previewTargetTitle(urlPreviewTarget('http://127.0.0.1:1/a.pdf'))).toBe('127.0.0.1')
    expect(previewTargetTitle(htmlPreviewTarget('<p>x</p>', '生成内容'))).toBe('生成内容')
  })
})

describe('preview resolve: native', () => {
  it.each([
    ['cover.png', 'image/png'],
    ['photo.jpeg', 'image/jpeg'],
    ['clip.mp4', 'video/mp4'],
    ['sound.mp3', 'audio/mpeg'],
    ['manual.pdf', 'application/pdf'],
    ['vector.svg', 'image/svg+xml'],
  ])('routes %s to the browser surface with %s', async (path, mime) => {
    const document_ = await resolvePreviewDocument(filePreviewTarget(path, { workRoot: 'E:/p' }), fakeTransport())
    expect(document_.mode).toBe('native')
    if (document_.mode !== 'native') return
    expect(document_.mime).toBe(mime)
    expect(document_.title).toBe(path)
  })

  it('joins workRoot as work_root and asks for inline rendering', async () => {
    // user:“实测 read-reference 的响应头…FileResponse(..., filename=...) 带出 attachment
    // 会让 iframe 变成下载”+(解析层必须带上 inline=1，否则预览会退化成下载)。
    const document_ = await resolvePreviewDocument(
      filePreviewTarget('E:/p/a.png', { workRoot: 'E:/p' }),
      fakeTransport(),
    )
    expect(document_.mode).toBe('native')
    if (document_.mode !== 'native') return
    const url = new URL(document_.url)
    expect(url.searchParams.get('path')).toBe('E:/p/a.png')
    expect(url.searchParams.get('work_root')).toBe('E:/p')
    expect(url.searchParams.get('inline')).toBe('1')
  })

  it('omits work_root when the target has no scope', async () => {
    const document_ = await resolvePreviewDocument(filePreviewTarget('E:/p/a.png'), fakeTransport())
    if (document_.mode !== 'native') throw new Error('expected native')
    expect(new URL(document_.url).searchParams.has('work_root')).toBe(false)
  })

  it('treats plain text and code as native text', async () => {
    for (const path of ['notes.txt', 'main.rs', 'config.yaml', 'data.json']) {
      const document_ = await resolvePreviewDocument(filePreviewTarget(path), fakeTransport())
      expect(document_.mode).toBe('native')
      if (document_.mode !== 'native') continue
      expect(document_.mime).toContain('text/plain')
    }
  })

  it('refuses to inline when the transport has no absolute backend origin', async () => {
    // user:“URL 只允许 http://127.0.0.1:<port> 与内部源”+(相对地址在同源托管下可用，
    // 但指向别处的地址不能冒充本机内联)。
    const document_ = await resolvePreviewDocument(
      filePreviewTarget('a.png'),
      fakeTransport({ url: (path: string) => `https://example.com${path}` }),
    )
    expect(document_.mode).toBe('unsupported')
  })
})

describe('preview resolve: rendered', () => {
  it('renders markdown through the sanitizing converter', async () => {
    const markdown = '# 标题\n\n正文一段\n\n- 一\n- 二\n'
    const document_ = await resolvePreviewDocument(
      filePreviewTarget('README.md', { workRoot: 'E:/p' }),
      fakeTransport({ read: vi.fn(async () => new TextEncoder().encode(markdown)) }),
    )
    expect(document_.mode).toBe('rendered')
    if (document_.mode !== 'rendered') return
    expect(document_.html).toContain('<h1>标题</h1>')
    expect(document_.html).toContain('<li>一</li>')
  })

  it('leaves no executable element or live remote resource in converted html', async () => {
    // user:“rendered 的 HTML 必须过白名单清理，禁止脚本、禁止远程资源引用”。
    // 转换器把原文里的 HTML 全量转义成纯文本，所以这里按 DOM 校验安全性质本身：
    // 解析后不能有脚本/图片/链接元素，也不存在指向远端的地址。
    const markdown = '# t\n\n<script>alert(1)</script>\n\n<img src="https://evil.example/x.png">\n\n[链接](https://evil.example/a)\n'
    const document_ = await resolvePreviewDocument(
      filePreviewTarget('x.md'),
      fakeTransport({ read: vi.fn(async () => new TextEncoder().encode(markdown)) }),
    )
    if (document_.mode !== 'rendered') throw new Error('expected rendered')
    const host = document.createElement('div')
    host.innerHTML = document_.html
    expect(host.querySelector('script')).toBeNull()
    expect(host.querySelector('img')).toBeNull()
    expect(host.querySelector('a')).toBeNull()
    expect(host.querySelector('[src], [href]')).toBeNull()
  })

  it('sanitizes an html target', async () => {
    const document_ = await resolvePreviewDocument(
      htmlPreviewTarget('<p onclick="x()">hi</p><script>bad()</script>', '生成内容'),
      fakeTransport(),
    )
    if (document_.mode !== 'rendered') throw new Error('expected rendered')
    expect(document_.html).not.toContain('<script')
    expect(document_.html).not.toContain('onclick')
    expect(document_.html).toContain('hi')
  })

  it('reports a read failure as unsupported instead of a blank frame', async () => {
    const document_ = await resolvePreviewDocument(
      filePreviewTarget('x.md'),
      fakeTransport({ read: vi.fn(async () => { throw new Error('原文件不存在') }) }),
    )
    expect(document_.mode).toBe('unsupported')
    if (document_.mode !== 'unsupported') return
    expect(document_.reason).toContain('原文件不存在')
  })
})

describe('preview resolve: unsupported', () => {
  it.each([
    ['report.docx'],
    ['budget.xlsx'],
    ['deck.pptx'],
    ['clip.mkv'],
  ])('explains why %s cannot be viewed and suggests the default app', async path => {
    const document_ = await resolvePreviewDocument(filePreviewTarget(path), fakeTransport())
    expect(document_.mode).toBe('unsupported')
    if (document_.mode !== 'unsupported') return
    expect(document_.reason).toContain('默认应用打开')
    expect(document_.title).toBe(path)
  })

  it('falls back to unsupported for unknown types', async () => {
    const document_ = await resolvePreviewDocument(filePreviewTarget('archive.zip'), fakeTransport())
    expect(document_.mode).toBe('unsupported')
    if (document_.mode !== 'unsupported') return
    expect(document_.reason).toContain('无法直接显示')
  })

  it('rejects dangerous schemes in the path', async () => {
    for (const path of ['javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,x']) {
      const document_ = await resolvePreviewDocument(filePreviewTarget(path), fakeTransport())
      expect(document_.mode).toBe('unsupported')
    }
  })

  it('does not preview external web pages', async () => {
    // user:“灯箱不提供任何浏览能力…只呈现 resolve.ts 给出的本地内容”+
    // (外部站点既嵌不进来，也不该由预览器承担)。
    const document_ = await resolvePreviewDocument(urlPreviewTarget('https://example.com/a'), fakeTransport())
    expect(document_.mode).toBe('unsupported')
    if (document_.mode !== 'unsupported') return
    expect(document_.reason).toContain('浏览器')
  })

  it('still allows a loopback url target', async () => {
    const document_ = await resolvePreviewDocument(urlPreviewTarget('http://127.0.0.1:52341/api/core/x/a.pdf'), fakeTransport())
    expect(document_.mode).toBe('native')
  })
})

describe('preview url guard', () => {
  it('accepts internal sources only', () => {
    expect(isInternalPreviewUrl('about:srcdoc')).toBe(true)
    expect(isInternalPreviewUrl('blob:http://127.0.0.1:1/abc')).toBe(true)
    expect(isInternalPreviewUrl('/api/core/files/read-reference?path=a')).toBe(true)
    expect(isInternalPreviewUrl('http://127.0.0.1:52341/api/core/x')).toBe(true)
    expect(isInternalPreviewUrl('http://localhost:5173/x')).toBe(true)
    expect(isInternalPreviewUrl('https://example.com/x')).toBe(false)
    expect(isInternalPreviewUrl('file:///c:/x.png')).toBe(false)
    expect(isInternalPreviewUrl('javascript:alert(1)')).toBe(false)
    expect(isInternalPreviewUrl('//example.com/x')).toBe(false)
    expect(isInternalPreviewUrl('')).toBe(false)
  })

  it('flags dangerous references', () => {
    expect(isDangerousReference('javascript:alert(1)')).toBe(true)
    expect(isDangerousReference('FILE:///x')).toBe(true)
    expect(isDangerousReference('E:/p/a.png')).toBe(false)
  })
})

describe('preview mime helpers', () => {
  it('maps extensions to mime and null for unknown', () => {
    expect(nativeMimeFor('a.PNG')).toBe('image/png')
    expect(nativeMimeFor('a.pdf')).toBe('application/pdf')
    expect(nativeMimeFor('a.txt')).toBeNull()
    expect(nativeMimeFor('a.docx')).toBeNull()
  })

  it('labels mime families for the lightbox header', () => {
    expect(previewMimeLabel('image/png')).toBe('图片')
    expect(previewMimeLabel('video/mp4')).toBe('视频')
    expect(previewMimeLabel('audio/mpeg')).toBe('音频')
    expect(previewMimeLabel('application/pdf')).toBe('PDF')
    expect(previewMimeLabel('text/plain; charset=utf-8')).toBe('文本')
    expect(previewMimeLabel('')).toBe('文件')
  })
})

describe('sanitizePreviewHtml', () => {
  it('keeps local content and drops script/iframe/form', () => {
    const html = sanitizePreviewHtml(
      '<p>ok</p><script>x()</script><iframe src="http://127.0.0.1:1/x"></iframe><form action="/x"><input></form>',
    )
    expect(html).toContain('ok')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('<iframe')
    expect(html).not.toContain('<form')
  })

  it('keeps loopback images and drops remote ones', () => {
    const html = sanitizePreviewHtml(
      '<img src="http://127.0.0.1:52341/a.png"><img src="https://cdn.example/b.png">',
    )
    expect(html).toContain('127.0.0.1:52341/a.png')
    expect(html).not.toContain('cdn.example')
  })
})
