import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, test } from 'vitest'

const root = resolve(import.meta.dirname, '..')
const source = readFileSync(resolve(root, 'src/components/MarkdownRenderer.vue'), 'utf8')
const katexCss = readFileSync(resolve(root, 'node_modules/katex/dist/katex.min.css'), 'utf8')

/**
 * user:“还是坏的，我刚才说正常了指的是你那会开的 dev 内正常了。我现在打包版更新到 36 依旧无法正常显示”+
 * (打包版主窗口走 Tauri 内嵌协议，那里这份独立的 KaTeX 样式表请求没有送达；dev 走 vite 的 http 所以正常。
 *  验收标准：KaTeX 样式必须由源码里的一份字符串随模块带进来，注入后不再依赖任何独立样式表请求，
 *  字体指向随应用发布的固定路径。)
 */
describe('KaTeX 样式随模块内联注入', () => {
  test('KaTeX 自带样式包含决定公式布局与字形的规则', () => {
    expect(katexCss.length).toBeGreaterThan(20000)
    expect(katexCss).toContain('.katex-mathml')
    expect(katexCss).toContain('.vlist')
    expect(katexCss).toContain('@font-face')
  })

  test('组件不再用裸样式表导入，改为读取样式源码文本', () => {
    expect(source).not.toContain("import 'katex/dist/katex.min.css'")
    expect(source).toContain("from 'katex/dist/katex.min.css?raw'")
  })

  test('字体地址改写成随应用发布的固定路径', () => {
    expect(source).toContain('/url\\(')
    expect(source).toContain('fonts\\/')
    expect(source).toContain("'url($1/katex-fonts/'")
  })

  test('组件在模块加载时把样式挂到 document.head，且只挂一次', () => {
    expect(source).toContain('document.getElementById(KATEX_INLINE_STYLE_ID)')
    expect(source).toContain('document.head.appendChild(style)')
    expect(source).toMatch(/style\.textContent\s*=\s*KATEX_STYLES/)
  })
})
