// @vitest-environment jsdom
/**
 * user:“目前仅预览就行，但是PPT能够正常预览吗？不能就去做”+
 * user:“这要求每个客户端都要有LibreOffice吗？”+
 * (验收：不再依赖本机任何 Office 程序。PPTX 里的占位符要顺着 版式 → 母版 → 主题 继承出
 *  坐标与字号，形状的位置、填充、文字、项目符号、表格都要解析成可直接绘制的数据)。
 */
import { expect, it } from 'vitest'
import { strToU8 } from 'fflate'
import { lengthCqw, parsePptxLayout } from '../src/preview/pptxLayout'

const NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

function deckParts(): Record<string, Uint8Array> {
  return {
    'ppt/presentation.xml': strToU8(`<p:presentation ${NS}><p:sldSz cx="9144000" cy="6858000"/></p:presentation>`),
    'ppt/theme/theme1.xml': strToU8(
      `<a:theme ${NS}><a:themeElements><a:clrScheme name="deck">`
      + '<a:dk1><a:sysClr val="windowText" lastClr="101010"/></a:dk1>'
      + '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
      + '<a:accent1><a:srgbClr val="2B3A67"/></a:accent1>'
      + '</a:clrScheme><a:fontScheme name="deck"><a:majorFont><a:latin typeface="Deck Major"/></a:majorFont>'
      + '<a:minorFont><a:latin typeface="Deck Minor"/></a:minorFont></a:fontScheme></a:themeElements></a:theme>',
    ),
    'ppt/slideMasters/slideMaster1.xml': strToU8(
      `<p:sldMaster ${NS}><p:cSld><p:spTree>`
      + '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
      + '<p:spPr><a:xfrm><a:off x="400000" y="300000"/><a:ext cx="8000000" cy="1000000"/></a:xfrm></p:spPr>'
      + '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>母版标题</a:t></a:r></a:p></p:txBody></p:sp>'
      + '</p:spTree></p:cSld>'
      + '<p:txStyles>'
      + '<p:titleStyle><a:lvl1pPr algn="ctr"><a:defRPr sz="4000"/></a:lvl1pPr></p:titleStyle>'
      + '<p:bodyStyle><a:lvl1pPr marL="342900" indent="-342900"><a:buChar char="•"/><a:defRPr sz="2800"/></a:lvl1pPr></p:bodyStyle>'
      + '<p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle>'
      + '</p:txStyles></p:sldMaster>',
    ),
    'ppt/slideLayouts/slideLayout1.xml': strToU8(
      `<p:sldLayout ${NS}><p:cSld><p:spTree>`
      + '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
      + '<p:spPr><a:xfrm><a:off x="457200" y="274638"/><a:ext cx="8229600" cy="1143000"/></a:xfrm></p:spPr>'
      + '<p:txBody><a:bodyPr anchor="ctr"/><a:lstStyle/><a:p><a:r><a:t>版式标题</a:t></a:r></a:p></p:txBody></p:sp>'
      + '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Content"/><p:cNvSpPr/><p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr>'
      + '<p:spPr><a:xfrm><a:off x="457200" y="1600200"/><a:ext cx="8229600" cy="4525963"/></a:xfrm></p:spPr>'
      + '<p:txBody><a:bodyPr/><a:lstStyle><a:lvl1pPr><a:defRPr sz="2400"/></a:lvl1pPr></a:lstStyle>'
      + '<a:p><a:r><a:t>版式正文</a:t></a:r></a:p></p:txBody></p:sp>'
      + '</p:spTree></p:cSld></p:sldLayout>',
    ),
    'ppt/slides/slide1.xml': strToU8(
      `<p:sld ${NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:schemeClr val="lt1"/></a:solidFill></p:bgPr></p:bg><p:spTree>`
      + '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title Box"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
      + '<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>季度汇报</a:t></a:r></a:p></p:txBody></p:sp>'
      + '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr/><p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr>'
      + '<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>'
      + '<a:p><a:r><a:t>第一点</a:t></a:r></a:p><a:p><a:r><a:t>第二点</a:t></a:r></a:p></p:txBody></p:sp>'
      + '<p:sp><p:nvSpPr><p:cNvPr id="4" name="Block"/><p:cNvSpPr/></p:nvSpPr>'
      + '<p:spPr><a:xfrm><a:off x="1000000" y="2000000"/><a:ext cx="2000000" cy="1000000"/></a:xfrm>'
      + '<a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>'
      + '<a:solidFill><a:schemeClr val="accent1"><a:lumMod val="60000"/></a:schemeClr></a:solidFill>'
      + '<a:ln w="25400"><a:solidFill><a:srgbClr val="C0392B"/></a:solidFill></a:ln></p:spPr></p:sp>'
      + '</p:spTree></p:cSld></p:sld>',
    ),
    'ppt/slides/_rels/slide1.xml.rels': strToU8(
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      + '<Relationship Id="rId1" Type="slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>',
    ),
  }
}

const deck = () => parsePptxLayout(deckParts())

it('占位符的位置与字号从版式/母版继承出来', () => {
  const parsed = deck()
  expect(parsed.width).toBe(9144000)
  const slide = parsed.slides[0]!
  const title = slide.shapes.find(shape => shape.text?.paragraphs[0]?.runs[0]?.text === '季度汇报')
  expect(title).toBeTruthy()
  // 标题占位符自己没有 xfrm：坐标来自版式。
  expect(title!.x).toBe(457200)
  expect(title!.y).toBe(274638)
  expect(title!.w).toBe(8229600)
  // 字号来自母版 titleStyle（40pt）。
  expect(title!.text!.paragraphs[0]!.runs[0]!.size).toBe(40)
  expect(title!.text!.anchor).toBe('middle')
})

it('正文用母版的项目符号与 28pt，而版式只把字号改到 24pt', () => {
  const slide = deck().slides[0]!
  const body = slide.shapes.find(shape => shape.text?.paragraphs.length === 2)!
  const paragraph = body.text!.paragraphs[0]!
  expect(paragraph.bullet).toBe('•')
  // 版式覆盖母版的字号：24pt 生效，项目符号与悬挂缩进仍来自母版。
  expect(paragraph.size).toBe(24)
  expect(paragraph.marginLeft).toBeCloseTo(27, 3)
  expect(paragraph.indent).toBeCloseTo(-27, 3)
})

it('形状的填充、描边与圆角被读出来', () => {
  const block = deck().slides[0]!.shapes.find(shape => shape.kind === 'shape')!
  expect(block.geometry).toBe('roundRect')
  expect(block.fill).toMatch(/^#[0-9a-f]{6}$/i)
  expect(block.line?.color?.toLowerCase()).toBe('#c0392b')
  expect(block.line?.width).toBe(25400)
})

it('尺寸换算：字号与左边距按幻灯片宽度等比', () => {
  expect(lengthCqw(36, 9144000)).toBe('5.0000cqw')
  expect(lengthCqw(72, 9144000)).toBe('10.0000cqw')
})

it('解析不依赖整包结构：只有幻灯片也能出页', () => {
  const parts = deckParts()
  const onlySlides = { 'ppt/presentation.xml': parts['ppt/presentation.xml']!, 'ppt/slides/slide1.xml': parts['ppt/slides/slide1.xml']! }
  const parsed = parsePptxLayout(onlySlides as Record<string, Uint8Array>)
  expect(parsed.slides).toHaveLength(1)
  // 没有版式时，标题占位符拿不到坐标 -> 跳过它，但正文里的普通形状照画。
  expect(parsed.slides[0]!.shapes.some(shape => shape.kind === 'shape')).toBe(true)
})
