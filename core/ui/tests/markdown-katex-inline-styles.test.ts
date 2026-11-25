import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, test } from 'vitest'

const root = resolve(import.meta.dirname, '..')
const source = readFileSync(resolve(root, 'src/components/MarkdownRenderer.vue'), 'utf8')
const katexCss = readFileSync(resolve(root, 'node_modules/katex/dist/katex.min.css'), 'utf8')

/**
 * user:“装完了，依旧失败，直接排查可能原因：dev 显示正常，打包显示异常”+
 * (打包版窗口的 CSP 给 style-src 配了 nonce，按规范 nonce 存在时 'unsafe-inline' 失效，
 *  插入的 <style> 会被静默丢弃：元素在文档里、sheet 却是 null，公式因此散架。
 *  验收标准：KaTeX 样式以脚本构造的样式表挂到文档上，不依赖 <style>；字体指向随包发布的固定路径。)
 */
describe('KaTeX 样式随模块挂载', () => {
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

  test('优先用脚本构造的样式表挂载，绕开 style-src 的 nonce 限制', () => {
    expect(source).toContain('new CSSStyleSheet()')
    expect(source).toMatch(/replaceSync\(\s*KATEX_STYLES\s*\)/)
    expect(source).toContain('document.adoptedStyleSheets')
  })

  test('只挂一次，并在不支持的环境回退到 <style>', () => {
    expect(source).toContain('__sundayKatexStyleSheetMounted')
    expect(source).toContain('document.head.appendChild(style)')
    expect(source).toMatch(/style\.textContent\s*=\s*KATEX_STYLES/)
  })
})
