import { describe, expect, it } from 'vitest'
import { normalizeWebLink, linkifyTextNodes } from '../src/helpers/webLinks'

describe('outcome and Markdown links', () => {
  it('normalizes protocol-less domains and rejects local paths or unsafe schemes', () => {
    expect(normalizeWebLink('example.com/docs')).toBe('https://example.com/docs')
    expect(normalizeWebLink('example.design/docs')).toBe('https://example.design/docs')
    expect(normalizeWebLink('//example.com')).toBe('https://example.com/')
    for (const value of ['C:/file.txt', 'report.md', 'javascript:alert(1)', '../a.txt', 'file:///a']) expect(normalizeWebLink(value)).toBeNull()
  })
  it('makes plain domains clickable without touching code, links or filenames', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>example.com/docs，report.md</p><code>example.com</code><a href="https://example.com">example.com</a>'
    linkifyTextNodes(root)
    expect(root.querySelectorAll('a')).toHaveLength(2)
    expect(root.querySelector('p a')?.getAttribute('href')).toBe('https://example.com/docs')
    expect(root.querySelector('code')?.innerHTML).toBe('example.com')
  })
})
