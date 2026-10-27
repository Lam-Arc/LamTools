import { describe, expect, it } from 'vitest'
import { fileReference, referenceSpans, insertReferences, activeCompletion, replaceReference } from '../src/composer/fileReferences'

// user:“在添加时的光标位置插入 ：@文件名”+(先验证路径序列化、插入位置及触发边界)。
describe('inline absolute file references', () => {
  it('keeps spaces, Unicode and same-name paths unambiguous', () => {
    const paths = ['C:/资料 one/a.png', 'D:/资料/a.png']
    const text = paths.map(fileReference).join(' ')
    expect(referenceSpans(text).map(s => s.path)).toEqual(paths)
    expect(referenceSpans(text).map(s => s.name)).toEqual(['a.png', 'a.png'])
  })
  it('replaces selection and prepends with a newline when no caret exists', () => {
    expect(insertReferences('abcXYZdef', ['C:/a.png'], { start: 3, end: 6 }).text).toBe('abc @"C:/a.png" def')
    expect(insertReferences('正文', ['C:/a.png'], null).text).toBe('@"C:/a.png"\n正文')
  })
  it('does not parse references in code or URLs', () => {
    expect(referenceSpans('`@"C:/a.png"` https://x/@a')).toEqual([])
  })
  it('async completion replaces its original slot and never restores a deleted reference', () => {
    const initial = 'before ' + fileReference('pending://one/a.png') + ' after'
    expect(replaceReference(initial, 'pending://one/a.png', 'C:/a.png')).toEqual({ text: 'before @"C:/a.png" after', replaced: true })
    expect(replaceReference('user removed it', 'pending://one/a.png', 'C:/a.png')).toEqual({ text: 'user removed it', replaced: false })
  })
  it('only completes at whitespace boundaries, outside quotes and code', () => {
    for (const prefix of ['/', '@', '#']) expect(activeCompletion(`hello ${prefix}ab`, 9)?.trigger).toBe(prefix)
    for (const text of ['mail@ab', 'https://ab', '` @ab', '" @ab']) expect(activeCompletion(text, text.length)).toBeNull()
  })
})
