import { describe, expect, it } from 'vitest'
import { BrowserAddressError, DEFAULT_SEARCH_ENGINE, addressText, isBlockedScheme, resolveAddress, searchUrl } from '../src/split/browserAddress'

// user:“地址栏输入「天气」能搜到结果”“要像浏览器”+(输入分类是纯函数：20 个样例覆盖网址、localhost、域名、搜索词与危险协议)。
describe('browser address resolution', () => {
  it('treats full web addresses as urls', () => {
    for (const raw of ['https://example.com/docs', 'http://example.com', 'HTTPS://Example.com/A']) {
      const result = resolveAddress(raw)
      expect(result.kind, raw).toBe('url')
      expect(result.url.startsWith('http'), raw).toBe(true)
    }
  })

  it('opens bare domains over https', () => {
    for (const raw of ['example.com', 'example.com/path?q=1', 'sub.example.co.uk']) {
      const result = resolveAddress(raw)
      expect(result.kind, raw).toBe('url')
      expect(result.url.startsWith('https://'), raw).toBe(true)
    }
  })

  it('opens local targets over plain http', () => {
    const cases: Array<[string, string]> = [
      ['localhost', 'http://localhost/'],
      ['localhost:3000', 'http://localhost:3000/'],
      ['127.0.0.1:5173', 'http://127.0.0.1:5173/'],
      ['192.168.1.1', 'http://192.168.1.1/'],
      ['192.168.1.1:8080/admin', 'http://192.168.1.1:8080/admin'],
    ]
    for (const [raw, expected] of cases) {
      expect(resolveAddress(raw), raw).toEqual({ kind: 'url', url: expected })
    }
  })

  it('searches keywords, including Chinese and spaced input', () => {
    for (const raw of ['天气', '好用的 网站', 'rust cargo build', 'hello']) {
      const result = resolveAddress(raw)
      expect(result.kind, raw).toBe('search')
      expect(result.url.startsWith('https://'), raw).toBe(true)
      expect(result.url.includes(' '), raw).toBe(false)
    }
  })

  it('percent-encodes search queries', () => {
    expect(searchUrl(DEFAULT_SEARCH_ENGINE, 'a b&c')).toContain('a%20b%26c')
    expect(resolveAddress('好用的 网站').url).toContain(encodeURIComponent('好用的 网站'))
  })

  it('rejects dangerous schemes instead of searching them', () => {
    for (const raw of [
      'file:///C:/Windows', 'javascript:alert(1)', 'data:text/html,x', 'tauri://localhost',
      'asset://localhost/x.png', 'about:blank', 'blob:https://example.com/uuid',
      'mailto:someone@example.com', 'ipc://localhost/x', 'ws://example.com/socket',
    ]) {
      let error: unknown
      try { resolveAddress(raw) } catch (cause) { error = cause }
      expect(error, raw).toBeInstanceOf(BrowserAddressError)
      expect((error as BrowserAddressError).code, raw).toBe('blocked_scheme')
    }
  })

  it('reports malformed web addresses', () => {
    for (const raw of ['https://', 'http://', 'https://?q=1']) {
      let error: unknown
      try { resolveAddress(raw) } catch (cause) { error = cause }
      expect(error, raw).toBeInstanceOf(BrowserAddressError)
    }
  })

  it('rejects empty input', () => {
    expect(() => resolveAddress('   ')).toThrow(BrowserAddressError)
  })

  it('flags blocked schemes for the interface without throwing', () => {
    expect(isBlockedScheme('javascript:alert(1)')).toBe(true)
    expect(isBlockedScheme('file:///C:/')).toBe(true)
    expect(isBlockedScheme('https://example.com')).toBe(false)
    expect(isBlockedScheme('example.com')).toBe(false)
  })
})

// user:“浏览器地址栏里显示出 [object Object] 文本（不是输入的网址）”+
// (地址栏的兜底取字符串只对字符串生效：非字符串一律回落到调用方给的上一次有效地址，
//  绝不用 String(对象) 兜底 —— 那正好就是 `[object Object]`)。
describe('address text narrowing', () => {
  it('returns strings untouched', () => {
    expect(addressText('https://example.com/a')).toBe('https://example.com/a')
    expect(addressText('')).toBe('')
  })

  it('falls back for everything that is not a string', () => {
    const fallback = 'https://example.com/last'
    for (const value of [{ href: 'https://evil.invalid/' }, ['https://evil.invalid/'], 42, 0, true, null, undefined, () => 'x']) {
      const text = addressText(value, fallback)
      expect(text, String(typeof value)).toBe(fallback)
      expect(text).not.toContain('[object Object]')
    }
  })

  it('defaults to an empty address so a blank bar is shown instead of an object', () => {
    expect(addressText({ href: 'https://example.com' })).toBe('')
    expect(addressText(undefined)).toBe('')
  })
})
