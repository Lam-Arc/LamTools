import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import FileTypeBadge from '../src/components/FileTypeBadge.vue'
import { fileExtension, fileTypeBadge } from '../src/helpers/fileTypeBadge'

describe('file type badge', () => {
  it('maps common extensions to editor-style labels and colours', () => {
    // user:“把那个@的符号去掉 换成对应的文件图标”+(TS/V/CSS/JS 等类型用彩色小方块表示)。
    expect(fileTypeBadge('editorHeight.ts')).toMatchObject({ label: 'TS', background: '#3178C6' })
    expect(fileTypeBadge('InlineFileComposer.vue').label).toBe('V')
    expect(fileTypeBadge('layout.css').label).toBe('CSS')
    expect(fileTypeBadge('app.js').label).toBe('JS')
    expect(fileTypeBadge('report.md').label).toBe('MD')
    expect(fileTypeBadge('photo.png').label).toBe('IMG')
    expect(fileExtension('C:\\project\\readme.MD')).toBe('md')
    expect(fileExtension('https://example.com/a.png?raw=1')).toBe('png')
    expect(fileTypeBadge('unknown.xyzxyz').label).toBe('XYZ')
  })

  it('keeps the label but turns the badge red for failed or missing files', () => {
    const normal = fileTypeBadge('photo.png')
    const failed = fileTypeBadge('photo.png', true)
    expect(failed.label).toBe(normal.label)
    expect(failed.background).toBe('#F5555D')
  })

  it('renders a 30%-rounded label badge without adding text to the file name', () => {
    const wrapper = mount(FileTypeBadge, { props: { name: 'a.ts', size: 18 } })
    expect(wrapper.attributes('style')).toContain('border-radius: 30%')
    expect(wrapper.attributes('data-label')).toBe('TS')
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.text()).toBe('')
  })
})
