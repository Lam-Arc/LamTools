import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import {
  DEFAULT_MESSAGE_STREAM,
  MESSAGE_STREAM_EXPORT_VERSION,
  exportMessageStreamJson,
  importMessageStreamJson,
  isNestedCardConflict,
  MESSAGE_STREAM_SIGNATURE_BORDER_WIDTH,
  messageStreamBorderedWidth,
  messageStreamCssVars,
  messageStreamRootAttrs,
  normalizeMessageStream,
} from '../src/helpers/messageStreamStyle.ts'

const __dirname = dirname(fileURLToPath(import.meta.url))

/** 契约里点名必须在根元素上落成的 data-* 属性。 */
const ROOT_ATTRS = [
  'data-ms-body-container',
  'data-ms-proc-title-container',
  'data-ms-proc-body-container',
  'data-ms-shimmer',
  'data-ms-shimmer-scope',
  'data-ms-theme-mode',
]

/** 契约里点名必须落成的 CSS 变量。 */
const CSS_VARS = [
  '--ms-body-font-family',
  '--ms-body-font-size',
  '--ms-body-line-height',
  '--ms-body-para-gap',
  '--ms-proc-title-font-family',
  '--ms-proc-title-font-size',
  '--ms-proc-title-icon',
  '--ms-proc-body-font-family',
  '--ms-proc-body-font-size',
  '--ms-proc-body-line-height',
  '--ms-proc-lines-1',
  '--ms-proc-lines-2',
  '--ms-proc-radius-sm',
  '--ms-proc-radius-lg',
  '--ms-proc-border-width',
  '--ms-proc-border-width-bordered',
  '--ms-proc-border-style',
  '--ms-proc-border-color',
  '--ms-proc-fill-color',
  '--ms-proc-fill-alpha',
  '--ms-proc-blur',
  '--ms-proc-shimmer-color',
  '--ms-proc-body-pad-y',
]

describe('消息流样式：默认值', () => {
  it('默认配置每一项都落在 PRD 的合法区间内', () => {
    const settings = normalizeMessageStream(DEFAULT_MESSAGE_STREAM)
    expect(settings.bodyFontSize).toBeGreaterThanOrEqual(12)
    expect(settings.bodyFontSize).toBeLessThanOrEqual(20)
    expect(settings.bodyLineHeight).toBeGreaterThanOrEqual(1.2)
    expect(settings.bodyLineHeight).toBeLessThanOrEqual(2)
    expect(settings.procTitleFontSize).toBeGreaterThanOrEqual(11)
    expect(settings.procTitleFontSize).toBeLessThanOrEqual(16)
    expect(settings.procBodyFontSize).toBeGreaterThanOrEqual(11)
    expect(settings.procBodyFontSize).toBeLessThanOrEqual(16)
    expect(settings.procBodyLineHeight).toBeGreaterThanOrEqual(1.2)
    expect(settings.procBodyLineHeight).toBeLessThanOrEqual(1.8)
    expect(settings.procLines1).toBeGreaterThanOrEqual(3)
    expect(settings.procLines1).toBeLessThanOrEqual(8)
    expect(settings.procLines2).toBeGreaterThanOrEqual(8)
    expect(settings.procLines2).toBeLessThanOrEqual(20)
    expect(settings.fillAlpha).toBeGreaterThanOrEqual(0)
    expect(settings.fillAlpha).toBeLessThanOrEqual(100)
    // 步长约束
    expect(settings.bodyFontSize % 1).toBe(0)
    expect(Number((settings.bodyLineHeight * 10).toFixed(6)) % 1).toBe(0)
    expect(settings.fillAlpha % 5).toBe(0)
  })

  it('过程行默认与既有兜底一致：6 / 10 / 1.65', () => {
    expect(DEFAULT_MESSAGE_STREAM.procLines1).toBe(6)
    expect(DEFAULT_MESSAGE_STREAM.procLines2).toBe(10)
    expect(DEFAULT_MESSAGE_STREAM.procBodyLineHeight).toBe(1.65)
    const vars = messageStreamCssVars(DEFAULT_MESSAGE_STREAM)
    expect(vars['--ms-proc-lines-1']).toBe('6')
    expect(vars['--ms-proc-lines-2']).toBe('10')
    expect(vars['--ms-proc-body-line-height']).toBe('1.65')
  })

  it('缺字段的老数据回落默认值，不抛错', () => {
    expect(normalizeMessageStream(undefined)).toEqual(DEFAULT_MESSAGE_STREAM)
    expect(normalizeMessageStream(null)).toEqual(DEFAULT_MESSAGE_STREAM)
    expect(normalizeMessageStream({})).toEqual(DEFAULT_MESSAGE_STREAM)
    // 只认识一个字段时，其余仍是默认值
    expect(normalizeMessageStream({ bodyFontSize: 18 }).bodyFontSize).toBe(18)
    expect(normalizeMessageStream({ bodyFontSize: 18 }).bodyLineHeight).toBe(DEFAULT_MESSAGE_STREAM.bodyLineHeight)
  })

  it('normalize 是幂等的（导出→导入→再导出不漂移）', () => {
    const once = normalizeMessageStream(DEFAULT_MESSAGE_STREAM)
    expect(once).toEqual(DEFAULT_MESSAGE_STREAM)
    expect(normalizeMessageStream(once)).toEqual(once)
  })

  it('默认值都在自己的吸附网格上（否则一保存就会漂移）', () => {
    const once = normalizeMessageStream(DEFAULT_MESSAGE_STREAM)
    for (const key of Object.keys(DEFAULT_MESSAGE_STREAM)) {
      expect(once[key], key).toEqual(DEFAULT_MESSAGE_STREAM[key])
    }
  })
})

describe('消息流样式：脏输入被夹紧', () => {
  it('数值越界夹到区间，非数字回落默认值', () => {
    const settings = normalizeMessageStream({
      bodyFontSize: 999,
      bodyLineHeight: 9,
      bodyParaGap: -40,
      procTitleFontSize: 3,
      procBodyFontSize: 99,
      procBodyLineHeight: 5,
      procLines1: -2,
      procLines2: 400,
      fillAlpha: 137,
    })
    expect(settings.bodyFontSize).toBe(20)
    expect(settings.bodyLineHeight).toBe(2)
    expect(settings.bodyParaGap).toBe(0)
    expect(settings.procTitleFontSize).toBe(11)
    expect(settings.procBodyFontSize).toBe(16)
    expect(settings.procBodyLineHeight).toBe(1.8)
    expect(settings.procLines1).toBe(3)
    expect(settings.procLines2).toBe(20)
    expect(settings.fillAlpha).toBe(100)
  })

  it('步长外的数值被吸附到最近的合法档位', () => {
    const settings = normalizeMessageStream({ bodyLineHeight: 1.63, fillAlpha: 37, bodyParaGap: 7 })
    // 行距按 0.05 吸附（0.1 网格会把默认值 1.65 改写成 1.6）
    expect(settings.bodyLineHeight).toBe(1.65)
    expect(settings.fillAlpha).toBe(35)
    // 步长 2：7 吸附到 8（Math.round(7 / 2) * 2）
    expect(settings.bodyParaGap).toBe(8)
  })

  it('非法枚举值回落默认值', () => {
    const settings = normalizeMessageStream({
      bodyContainer: 'floating',
      procTitleContainer: 'circle',
      procBodyContainer: 'panel',
      borderStyle: 'double',
      colorTheme: 'rainbow',
      shimmerScope: 'sometimes',
      bodyFont: 'comic',
    })
    expect(settings.bodyContainer).toBe(DEFAULT_MESSAGE_STREAM.bodyContainer)
    expect(settings.procTitleContainer).toBe(DEFAULT_MESSAGE_STREAM.procTitleContainer)
    expect(settings.procBodyContainer).toBe(DEFAULT_MESSAGE_STREAM.procBodyContainer)
    expect(settings.borderStyle).toBe(DEFAULT_MESSAGE_STREAM.borderStyle)
    expect(settings.colorTheme).toBe('mono')
    expect(settings.shimmerScope).toBe('running')
    expect(settings.bodyFont).toBe('system')
  })

  it('颜色只收 HEX / RGB，其它字符串被丢弃（不把任意 CSS 片段塞进变量）', () => {
    expect(normalizeMessageStream({ borderColor: '#8b5cf6' }).borderColor).toBe('#8b5cf6')
    expect(normalizeMessageStream({ borderColor: 'rgb(1, 2, 3)' }).borderColor).toBe('rgb(1, 2, 3)')
    expect(normalizeMessageStream({ borderColor: 'red; background: url(x)' }).borderColor).toBe('')
    expect(normalizeMessageStream({ fillColor: 'javascript:alert(1)' }).fillColor).toBe('')
  })

  it('自定义字体名只留安全字符', () => {
    const settings = normalizeMessageStream({ bodyFont: 'custom', bodyFontCustom: '"Evil"; } body {' })
    expect(settings.bodyFontCustom).not.toContain(';')
    expect(settings.bodyFontCustom).not.toContain('"')
    expect(settings.bodyFontCustom).not.toContain('{')
    expect(settings.bodyFontCustom).not.toContain('}')
  })
})

describe('消息流样式：容器强制规则', () => {
  it('胶囊形态固定 2px 描边', () => {
    const settings = normalizeMessageStream({
      procTitleContainer: 'pill',
      borderWidth: 1,
    })
    const vars = messageStreamCssVars(settings)
    expect(vars['--ms-proc-border-width']).toBe('2px')
    // 胶囊不影响「边框」模式那条
    expect(vars['--ms-proc-border-width-bordered']).toBe('1px')
    expect(MESSAGE_STREAM_SIGNATURE_BORDER_WIDTH).toBe(2)
  })

  it('卡片形态固定 2px 描边（正文卡片 / 过程行内容卡片都算）', () => {
    expect(messageStreamCssVars(normalizeMessageStream({ bodyContainer: 'card', borderWidth: 1 }))['--ms-proc-border-width'])
      .toBe('2px')
    expect(messageStreamCssVars(normalizeMessageStream({ procBodyContainer: 'card', borderWidth: 3 }))['--ms-proc-border-width'])
      .toBe('2px')
    // 卡片与边框同时存在时互不拉扯
    const mixed = messageStreamCssVars(normalizeMessageStream({
      bodyContainer: 'bordered',
      procBodyContainer: 'card',
      borderWidth: 1,
    }))
    expect(mixed['--ms-proc-border-width']).toBe('2px')
    expect(mixed['--ms-proc-border-width-bordered']).toBe('1px')
  })

  it('只有「边框」模式能吃到 1 / 1.5 / 2 / 3px', () => {
    for (const width of [1, 1.5, 2, 3]) {
      const settings = normalizeMessageStream({
        bodyContainer: 'bordered',
        procTitleContainer: 'none',
        procBodyContainer: 'none',
        borderWidth: width,
      })
      expect(messageStreamBorderedWidth(settings)).toBe(width)
      expect(messageStreamCssVars(settings)['--ms-proc-border-width-bordered']).toBe(`${width}px`)
      // 边框模式不改胶囊 / 卡片那条
      expect(messageStreamCssVars(settings)['--ms-proc-border-width']).toBe('2px')
    }
  })

  it('粗细只认 1 / 1.5 / 2 / 3，其它值吸附到最近的档位', () => {
    expect(normalizeMessageStream({ borderWidth: 7 }).borderWidth).toBe(3)
    expect(normalizeMessageStream({ borderWidth: 0.2 }).borderWidth).toBe(1)
    expect(normalizeMessageStream({ borderWidth: 1.7 }).borderWidth).toBe(1.5)
  })
})

describe('消息流样式：嵌套卡片降级', () => {
  it('正文卡片 + 过程行内容卡片才算冲突', () => {
    expect(isNestedCardConflict(normalizeMessageStream({ bodyContainer: 'card', procBodyContainer: 'card' }))).toBe(true)
    expect(isNestedCardConflict(normalizeMessageStream({ bodyContainer: 'card', procBodyContainer: 'bordered' }))).toBe(false)
    expect(isNestedCardConflict(normalizeMessageStream({ bodyContainer: 'bordered', procBodyContainer: 'card' }))).toBe(false)
    expect(isNestedCardConflict(normalizeMessageStream({ bodyContainer: 'card', procBodyContainer: 'none' }))).toBe(false)
  })

  it('冲突时内层填充透明度降一级，不冲突时与正常值一致', () => {
    const conflict = messageStreamCssVars(normalizeMessageStream({
      bodyContainer: 'card',
      procBodyContainer: 'card',
      fillAlpha: 60,
    }))
    const normal = messageStreamCssVars(normalizeMessageStream({
      bodyContainer: 'card',
      procBodyContainer: 'bordered',
      fillAlpha: 60,
    }))
    expect(normalizeFloat(conflict['--ms-proc-fill-alpha'])).toBe(60)
    expect(normalizeFloat(conflict['--ms-proc-fill-alpha-inner'])).toBe(40)
    expect(normalizeFloat(normal['--ms-proc-fill-alpha-inner'])).toBe(60)
  })

  it('透明度本来就低时内层不会被降成负数', () => {
    const vars = messageStreamCssVars(normalizeMessageStream({
      bodyContainer: 'card',
      procBodyContainer: 'card',
      fillAlpha: 10,
    }))
    expect(normalizeFloat(vars['--ms-proc-fill-alpha-inner'])).toBe(0)
  })
})

describe('消息流样式：导出 / 导入', () => {
  it('导出带版本号，导入后与原配置完全一致', () => {
    const settings = normalizeMessageStream({
      bodyFont: 'serif',
      bodyFontSize: 17,
      bodyLineHeight: 1.8,
      bodyContainer: 'card',
      procTitleContainer: 'pill',
      procBodyFont: 'mono',
      procBodyFontSize: 13,
      procLines1: 6,
      procLines2: 16,
      borderStyle: 'dashed',
      fillPreset: 'accent',
      fillAlpha: 65,
      blur: true,
      colorTheme: 'chromatic',
      shimmer: true,
      shimmerScope: 'always',
    })

    const json = exportMessageStreamJson(settings)
    const parsed = JSON.parse(json)
    expect(parsed.kind).toBe('lamtools.messageStream')
    expect(parsed.version).toBe(MESSAGE_STREAM_EXPORT_VERSION)

    const restored = importMessageStreamJson(json)
    expect(restored).toEqual(settings)
    // 往返两轮也不漂移
    expect(importMessageStreamJson(exportMessageStreamJson(restored))).toEqual(settings)
  })

  it('也接受直接粘贴裸设置对象', () => {
    const restored = importMessageStreamJson(JSON.stringify({ bodyFontSize: 18 }))
    expect(restored.bodyFontSize).toBe(18)
    expect(restored.bodyLineHeight).toBe(DEFAULT_MESSAGE_STREAM.bodyLineHeight)
  })

  it('坏 JSON 抛可读错误而不是炸掉界面', () => {
    expect(() => importMessageStreamJson('{ 这不是 JSON')).toThrow(/JSON/)
    expect(() => importMessageStreamJson('')).toThrow(/JSON/)
    expect(() => importMessageStreamJson('[]')).toThrow(/对象/)
    expect(() => importMessageStreamJson('"text"')).toThrow(/对象/)
  })

  it('别的配置 / 过高的版本号给出明确错误', () => {
    expect(() => importMessageStreamJson(JSON.stringify({ kind: 'other.tool', settings: {} }))).toThrow(/消息流/)
    expect(() => importMessageStreamJson(JSON.stringify({ version: 99, settings: {} }))).toThrow(/版本/)
  })

  it('导入越界字段被夹紧而不是报错', () => {
    const restored = importMessageStreamJson(JSON.stringify({
      kind: 'lamtools.messageStream',
      version: 1,
      settings: { bodyFontSize: 999, bodyContainer: 'nope' },
    }))
    expect(restored.bodyFontSize).toBe(20)
    expect(restored.bodyContainer).toBe('none')
  })
})

describe('消息流样式：落成根元素契约', () => {
  it('data-* 属性齐全且取值合法', () => {
    const attrs = messageStreamRootAttrs(normalizeMessageStream({
      bodyContainer: 'card',
      procTitleContainer: 'pill',
      procBodyContainer: 'bordered',
      shimmer: true,
      shimmerScope: 'always',
    }), 'dark')

    for (const name of ROOT_ATTRS) expect(attrs[name]).toBeDefined()
    expect(attrs['data-ms-body-container']).toBe('card')
    expect(attrs['data-ms-proc-title-container']).toBe('pill')
    expect(attrs['data-ms-proc-body-container']).toBe('bordered')
    expect(attrs['data-ms-shimmer']).toBe('1')
    expect(attrs['data-ms-shimmer-scope']).toBe('always')
    expect(attrs['data-ms-theme-mode']).toBe('dark')
    expect(Object.keys(attrs).sort()).toEqual([...ROOT_ATTRS].sort())
  })

  it('流光关闭时 data-ms-shimmer 是 0', () => {
    expect(messageStreamRootAttrs(normalizeMessageStream({ shimmer: false }))['data-ms-shimmer']).toBe('0')
    expect(messageStreamRootAttrs(normalizeMessageStream({ shimmer: true }))['data-ms-shimmer']).toBe('1')
  })

  it('CSS 变量齐全', () => {
    const vars = messageStreamCssVars(DEFAULT_MESSAGE_STREAM)
    for (const name of CSS_VARS) expect(vars[name], name).toBeDefined()
    expect(vars['--ms-body-font-size']).toBe('14px')
    expect(vars['--ms-proc-body-pad-y']).toBe('10px')
    expect(vars['--ms-proc-title-icon']).toBe('1')
  })

  it('图标开关落成 1/0，过程行行数原样落成数字', () => {
    const off = messageStreamCssVars(normalizeMessageStream({ procTitleIcon: false, procLines1: 7, procLines2: 18 }))
    expect(off['--ms-proc-title-icon']).toBe('0')
    expect(off['--ms-proc-lines-1']).toBe('7')
    expect(off['--ms-proc-lines-2']).toBe('18')
  })

  it('幻彩色阶跟随 themeMode 自动切换，不接受手动挑选', () => {
    const settings = normalizeMessageStream({ colorTheme: 'chromatic' })
    const light = messageStreamCssVars(settings, { themeMode: 'light' })
    const dark = messageStreamCssVars(settings, { themeMode: 'dark' })
    expect(light['--ms-proc-fill-color']).not.toBe(dark['--ms-proc-fill-color'])
    expect(light['--ms-proc-border-color']).not.toBe(dark['--ms-proc-border-color'])
    expect(light['--ms-proc-fill-gradient']).toContain('linear-gradient')
    expect(dark['--ms-proc-fill-gradient']).toContain('linear-gradient')
    // 同一份配置 + 同一个模式必须稳定
    expect(messageStreamCssVars(settings, { themeMode: 'dark' })).toEqual(dark)
  })

  it('毛玻璃开关落成 backdrop-filter 值', () => {
    expect(messageStreamCssVars(normalizeMessageStream({ blur: false }))['--ms-proc-blur']).toBe('none')
    expect(messageStreamCssVars(normalizeMessageStream({ blur: true }))['--ms-proc-blur']).toBe('blur(10px)')
  })
})

describe('消息流样式：样式表兜底', () => {
  const css = readFileSync(resolve(__dirname, '../src/styles/message-stream.css'), 'utf8')

  it(':root 给全套 --ms-* 默认值，未配置时界面也正常', () => {
    const rootBlock = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')))
    for (const name of CSS_VARS) expect(rootBlock, name).toContain(`${name}:`)
    // 高度公式要用到上下内边距
    expect(rootBlock).toContain('--ms-proc-height-1')
    expect(rootBlock).toContain('--ms-proc-body-pad-y')
  })

  it('高度变量是唯一真源，用 1em 跟随消费元素的行高', () => {
    expect(css).toContain('--ms-proc-height-1: calc(var(--ms-proc-lines-1) * var(--ms-proc-body-line-height) * 1em + 2 * var(--ms-proc-body-pad-y))')
    expect(css).toContain('--ms-proc-height-2: calc(var(--ms-proc-lines-2) * var(--ms-proc-body-line-height) * 1em + 2 * var(--ms-proc-body-pad-y))')
    expect(css).not.toContain('* var(--ms-proc-body-font-size)')
  })

  it('透明度变量是百分比字符串，CSS 里给了正确的消费示例', () => {
    expect(messageStreamCssVars(DEFAULT_MESSAGE_STREAM)['--ms-proc-fill-alpha']).toMatch(/%$/)
    expect(css).toContain('color-mix(in srgb, var(--ms-proc-fill-color) var(--ms-proc-fill-alpha), transparent)')
  })

  it('流光选择器以 :root[data-ms-*] 开头，并尊重减少动态效果', () => {
    expect(css).toContain(':root[data-ms-shimmer="1"]')
    expect(css).toContain('@keyframes ms-shimmer-flow')
    expect(css).toContain('prefers-reduced-motion: reduce')
    // 不允许写成 .thread[...]：属性写在 documentElement 上
    expect(css).not.toMatch(/\.thread\s*\[data-ms-/)
  })
})

/** '40%' → 40，方便比较透明度。 */
function normalizeFloat(value: string | undefined): number {
  return Number.parseFloat(String(value ?? '0').replace('%', ''))
}
