import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { COMPOSER_EDITOR_MAX_LINES, composerEditorMaxHeight } from '../src/composer/editorHeight'

const componentSource = readFileSync(
  resolve(import.meta.dirname, '../src/components/InlineFileComposer.vue'),
  'utf8',
)
const baseCssSource = readFileSync(
  resolve(import.meta.dirname, '../src/styles/base.css'),
  'utf8',
)
const layoutCssSource = readFileSync(
  resolve(import.meta.dirname, '../src/styles/layout.css'),
  'utf8',
)

describe('composer editor height cap', () => {
  it('caps the main composer at 8 content lines', () => {
    // user:“修复输入栏高度无上限的 bug，多行时可达 8 行高即为极限”
    // user:“不只是八行 我看那都超出屏幕了”+(上限仍是 8 行；修复的是个别 WebView
    // 没吃到主题限高，导致完全不受限)。
    expect(COMPOSER_EDITOR_MAX_LINES).toBe(8)
    expect(composerEditorMaxHeight()).toBe('calc(8 * 1.6em + 2 * 8px)')
  })

  it('applies the cap to the CodeMirror scroller, which keeps scrolling inside', () => {
    expect(componentSource).toContain('maxHeight: composerEditorMaxHeight()')
    expect(componentSource).toMatch(/'\.cm-scroller':\s*\{[^}]*overflow:\s*'auto'/)
  })

  it('writes the cap onto the scroller itself and as a static CSS fallback', () => {
    // user:“我看那都超出屏幕了”+(不能只依赖 CodeMirror 运行时注入的主题样式：
    // 限高同时写到滚动容器的内联样式和静态样式表，个别 WebView 没吃到主题也不会失控)。
    expect(componentSource).toContain('view.scrollDOM.style.maxHeight = composerEditorMaxHeight()')
    expect(componentSource).toContain("'--composer-editor-max-height': composerEditorMaxHeight()")
    const scrollerRule = layoutCssSource.match(
      /\.inline-file-composer \.cm-scroller\s*\{([^}]*)\}/,
    )
    expect(scrollerRule).not.toBeNull()
    expect(scrollerRule![1]).toMatch(
      /max-height:\s*var\(--composer-editor-max-height,\s*calc\(8 \* 1\.6em \+ 2 \* 8px\)\)/,
    )
  })

  it('keeps each uploaded file tag between 32px and 64px and hides the overflow', () => {
    // user:“上传附件之后，附件的标签没有做长度限制，容易把输入区撑满，导致难以
    // 点击继续输入，请把附件限制在 32px-64px 内，超出部分文字隐藏”+(每个文件
    // 标签固定为 32–64px 的小胶囊，长文件名显示省略号，完整名称留在 title 里)。
    const rule = layoutCssSource.match(
      /\.inline-file-composer \.composer-file-token\s*\{([^}]*)\}/,
    )
    expect(rule).not.toBeNull()
    const body = rule![1]
    expect(body).toMatch(/min-width:\s*32px/)
    expect(body).toMatch(/max-width:\s*64px/)
    expect(body).toMatch(/overflow:\s*hidden/)
    expect(body).toMatch(/text-overflow:\s*ellipsis/)
    expect(body).toMatch(/white-space:\s*nowrap/)
    expect(body).not.toMatch(/white-space:\s*normal/)
    expect(body).not.toMatch(/max-width:\s*100%/)
  })

  it('softens the typed question text below full glare', () => {
    // user:“修复输入栏中向 Sunday 提出问题的文字颜色过亮的问题”
    expect(componentSource).toMatch(
      /color:\s*'color-mix\(in srgb,\s*var\(--theme-composer-text\) 85%, transparent\)'/,
    )
    expect(componentSource).toMatch(
      /caretColor:\s*'color-mix\(in srgb,\s*var\(--theme-composer-text\) 85%, transparent\)'/,
    )
    // 占位符必须比正文更淡，保持层级
    expect(componentSource).toMatch(/\.cm-placeholder[^}]*45%,transparent/)
  })

  it('keeps the CodeMirror screen-reader announcement visually hidden', () => {
    // user:“修复输入栏中有时会出现什么什么什么 deleted 的问题”+(截图确认是
    // CodeMirror 删除选区时的读屏公告“Selection deleted”漏显示；官方隐藏依赖
    // position:fixed，WebView2 下可能失效，这里用 1×1 + 裁切的视觉隐藏兜底，
    // 读屏仍可播报、界面永不显示)。
    const rule = baseCssSource.match(/\.cm-announced\s*\{([^}]*)\}/)
    expect(rule).not.toBeNull()
    const body = rule![1]
    expect(body).toMatch(/overflow:\s*hidden/)
    expect(body).toMatch(/clip-path:\s*inset\(50%\)/)
    expect(body).toMatch(/width:\s*1px/)
    expect(body).toMatch(/height:\s*1px/)
    expect(body).toMatch(/pointer-events:\s*none/)
  })
})
