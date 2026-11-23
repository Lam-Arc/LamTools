import { describe, expect, it } from 'vitest'

import { classifyLink, opensInBrowser, wantsInternalBrowser } from '../src/browser/linkRouting'

// user:“只对 http(s) 生效；本地文件引用仍走预览器/编辑器”+
// (分类规则只有一份：这里把四条去处的边界钉死，入口实现只读结论)。
describe('browser link routing', () => {
  it('routes http(s) links into the built-in browser', () => {
    for (const href of ['https://example.com/a?b=1', 'http://127.0.0.1:8848/x', 'HTTPS://Example.COM']) {
      const decision = classifyLink(href)
      expect(decision.route).toBe('internal')
      expect(decision.url).toBe(href)
      expect(decision.reason).toContain('http(s)')
    }
  })

  it('keeps local file references out of the browser', () => {
    for (const href of [
      'attachment://abc123',
      'workspace://notes/a.md',
      'file:///C:/work/a.txt',
      'C:\\work\\a.md',
      'D:/work/b.png',
      './relative/c.md',
      '../up.md',
      'notes/a.md',
    ]) {
      const decision = classifyLink(href)
      expect(decision.route, href).toBe('local')
      expect(decision.reason).toContain('预览器/编辑器')
    }
  })

  it('hands non-http schemes to the system', () => {
    for (const href of ['mailto:a@b.com', 'tel:+8610000000000', 'magnet:?xt=urn:btih:abc']) {
      expect(classifyLink(href).route, href).toBe('external')
    }
  })

  it('never takes over anchors or script schemes', () => {
    expect(classifyLink('#section').route).toBe('ignore')
    expect(classifyLink('javascript:alert(1)').route).toBe('ignore')
    expect(classifyLink('data:text/html;base64,PHNjcmlwdD4=').route).toBe('ignore')
    expect(classifyLink('').route).toBe('ignore')
  })

  it('only advertises the entry for http(s)', () => {
    expect(opensInBrowser('https://example.com')).toBe(true)
    expect(opensInBrowser('/work/a.md')).toBe(false)
    expect(opensInBrowser('mailto:a@b.com')).toBe(false)
  })

  it('treats ctrl or cmd click as an explicit request for the built-in browser', () => {
    expect(wantsInternalBrowser({ ctrlKey: true })).toBe(true)
    expect(wantsInternalBrowser({ metaKey: true })).toBe(true)
    expect(wantsInternalBrowser({})).toBe(false)
    expect(wantsInternalBrowser({ ctrlKey: false, metaKey: false })).toBe(false)
  })
})
