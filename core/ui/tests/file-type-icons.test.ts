import { describe, expect, it } from 'vitest'
import { fileCategory, fileTypeIconMarkup } from '../src/helpers/fileTypeIcon'

// user:“重新设计各附件的图标，最好一眼就能看出来这是个什么类型文件”+
// (每个扩展名都要落到明确类别；小图标、胶囊、卡片共用同一套图形)。
describe('file type icons', () => {
  it.each([
    ['photo.png', 'image'],
    ['photo.JPG', 'image'],
    ['cover.svg', 'image'],
    ['clip.mp4', 'video'],
    ['voice.wav', 'audio'],
    ['manual.pdf', 'pdf'],
    ['brief.docx', 'word'],
    ['legacy.doc', 'word'],
    ['sheet.xlsx', 'sheet'],
    ['data.csv', 'sheet'],
    ['deck.pptx', 'presentation'],
    ['bundle.zip', 'archive'],
    ['notes.md', 'markdown'],
    ['main.py', 'code'],
    ['settings.json', 'json'],
    ['page.html', 'html'],
    ['readme.txt', 'text'],
    ['unknown.bin', 'file'],
  ])('classifies %s as %s', (name, category) => {
    expect(fileCategory(name)).toBe(category)
  })

  it('draws distinct glyphs for PDF, plain text and HTML', () => {
    const pdf = fileTypeIconMarkup('manual.pdf', 16)
    const text = fileTypeIconMarkup('readme.txt', 16)
    const html = fileTypeIconMarkup('page.html', 16)
    expect(pdf).toContain('<svg')
    expect(pdf).not.toBe(text)
    expect(html).not.toBe(text)
    // Icon-only: the markup must not carry the file name as text content.
    expect(pdf).not.toContain('manual.pdf')
  })

  it('honours the requested size for small, pill and card usage', () => {
    expect(fileTypeIconMarkup('a.png', 12)).toContain('width="12" height="12"')
    expect(fileTypeIconMarkup('a.png', 24)).toContain('width="24" height="24"')
    expect(fileTypeIconMarkup('a.png', 44)).toContain('width="44" height="44"')
  })
})
