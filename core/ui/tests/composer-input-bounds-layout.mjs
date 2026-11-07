// user:“在复制进去一长段文本的时候，会把输入栏撑至巨大，而不是正常的高度限制”
// user:“上传附件之后，附件的标签没有做长度限制，容易把输入区撑满……请把附件限制在
// 32px-64px 内，超出部分文字隐藏”
// +(用本地浏览器引擎量真实布局：粘贴长文后编辑区最多 8 行并在框内滚动；单个文件
// 标签宽度落在 32–64px，长文件名用省略号收起。)
import { createServer } from 'vite'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import assert from 'node:assert/strict'

const directory = mkdtempSync(join(tmpdir(), 'lam-composer-bounds-'))
const page = `<!doctype html><meta charset="utf-8"><div id="app"></div><pre id="result">loading</pre><script type="module" src="/__bounds_entry.js"></script>`
const entry = `
import { createApp, h, ref, nextTick } from 'vue'
import ComposerBar from '/src/components/ComposerBar.vue'
import Editor from '/src/components/InlineFileComposer.vue'
import ReferenceItems from '/src/components/ReferenceItems.vue'
import { renderFileReferenceNodes } from '/src/helpers/fileReferenceRendering.ts'
import '/src/styles/variables.css'; import '/src/styles/base.css'; import '/src/styles/layout.css';
const longName = 'this-is-an-extremely-long-attachment-file-name-that-should-not-fill-the-input-area-at-all.png'
const longPath = 'C:/tmp/' + longName
const attachments = [{ id: 'a1', filename: longName, label: longName, path: longPath, mime_type: 'image/png', preview_type: 'image', size: 1, status: 'uploaded' }]
const draft = ref('')
const outcomeArtifacts = Array.from({ length: 8 }, (_, index) => ({ artifact_id: 'outcome-' + index, name: 'result-' + index + '.ts', kind: 'file', path: '', metadata: {} }))
createApp({ setup(){ return ()=>h('div',{class:'workspace-shell workspace-shell--composer-center',style:'--main-left:0px;--main-right:0px;--content-width:780px'},[
  h(ComposerBar,{variant:'floating'},{ textarea:()=>h(Editor,{modelValue:draft.value,'onUpdate:modelValue':value=>draft.value=value,attachments,placeholder:'输入内容...'}) }),
  h('div',{class:'outcome-fixture'},[
    h(ReferenceItems,{ artifacts: outcomeArtifacts, transport: { request: async () => ({ status: 404, headers: {}, body: new Uint8Array() }) } })
  ])
]) } }).mount('#app')
try {
  await nextTick()
  const form = document.querySelector('.floating-composer')
  const editor = document.querySelector('[role=textbox]')
  const scroller = document.querySelector('.cm-scroller')
  editor.focus()
  // 模拟 constant 实例里“主题样式没生效”的情况：先把注入主题里的
  // .cm-scroller max-height 规则拿掉（保留静态样式表里的 .inline-file-composer 规则），
  // 再粘贴长文，验证内联/静态限高仍然兜住。
  for (const sheet of document.styleSheets) {
    try {
      for (const rule of sheet.cssRules) {
        const selector = rule.selectorText || ''
        if (selector.includes('.cm-scroller') && !selector.includes('.inline-file-composer') && rule.style.maxHeight) {
          rule.style.removeProperty('max-height')
        }
      }
    } catch {}
  }
  document.execCommand('insertText', false, '这是一段很长的文本，用来测试输入栏高度。'.repeat(300))
  await new Promise(r=>setTimeout(r,200))
  const style = getComputedStyle(scroller)
  const lineHeight = Number.parseFloat(style.lineHeight) || 0
  const eightLineCap = lineHeight * 8 + 16
  const longText = {
    formHeight: form.getBoundingClientRect().height,
    scrollerHeight: scroller.clientHeight,
    scrollerScrollHeight: scroller.scrollHeight,
    inlineMaxHeight: scroller.style.maxHeight,
    scrollerMaxHeight: style.maxHeight,
    lineHeight,
    eightLineCap,
  }
  // 再验证第二层兜底：连内联样式也拿掉，静态样式表的 8 行上限仍然生效。
  scroller.style.maxHeight = ''
  await new Promise(r=>setTimeout(r,80))
  const staticStyle = getComputedStyle(scroller)
  const staticOnly = {
    scrollerHeight: scroller.clientHeight,
    scrollerScrollHeight: scroller.scrollHeight,
    scrollerMaxHeight: staticStyle.maxHeight,
  }
  draft.value = ''
  await nextTick()
  await new Promise(r=>setTimeout(r,60))
  draft.value = '@' + JSON.stringify(longPath)
  await new Promise(r=>setTimeout(r,200))
  const token = document.querySelector('.composer-file-token')
  const tokenStyle = token ? getComputedStyle(token) : null
  const tokenRect = token ? token.getBoundingClientRect() : null
  const badge = token ? token.querySelector('.composer-file-badge') : null
  const attachmentTag = token ? {
    width: tokenRect.width,
    minWidth: tokenStyle.minWidth,
    maxWidth: tokenStyle.maxWidth,
    overflow: tokenStyle.overflow,
    textOverflow: tokenStyle.textOverflow,
    whiteSpace: tokenStyle.whiteSpace,
    title: token.title,
    formHeight: form.getBoundingClientRect().height,
    badgeLabel: badge ? badge.dataset.label : '',
    badgeRadius: badge ? getComputedStyle(badge).borderRadius : '',
    badgeContent: badge ? getComputedStyle(badge, '::before').content : '',
    tokenText: token.textContent,
  } : null
  const host = document.createElement('div')
  host.innerHTML = '<p>@"C:/tmp/a.ts" 与 docs/report.md</p>'
  document.querySelector('#app').appendChild(host)
  renderFileReferenceNodes(host, 'C:/tmp')
  const refBadge = host.querySelector('.file-reference-badge')
  const messageReference = {
    text: host.textContent,
    labels: [...host.querySelectorAll('.file-reference-badge')].map(node => node.dataset.label),
    radius: refBadge ? getComputedStyle(refBadge).borderRadius : '',
    content: refBadge ? getComputedStyle(refBadge, '::before').content : '',
  }
  const outcomeFixture = document.querySelector('.outcome-fixture')
  const countOutcome = () => outcomeFixture.querySelectorAll('.reference-item:not(.reference-item--more)').length
  const outcomeToggle = outcomeFixture.querySelector('[data-reference-toggle]')
  const firstOutcomeBadge = outcomeFixture.querySelector('.file-type-badge')
  const outcome = {
    initial: countOutcome(),
    toggle: outcomeToggle ? outcomeToggle.textContent : '',
    badges: outcomeFixture.querySelectorAll('.file-type-badge').length,
    radius: firstOutcomeBadge ? getComputedStyle(firstOutcomeBadge).borderRadius : '',
  }
  outcomeToggle?.click()
  await new Promise(r=>setTimeout(r,80))
  outcome.expanded = countOutcome()
  outcome.expandedLabel = outcomeFixture.querySelector('[data-reference-toggle]')?.textContent || ''
  outcomeFixture.querySelector('[data-reference-toggle]')?.click()
  await new Promise(r=>setTimeout(r,80))
  outcome.collapsedAgain = countOutcome()
  document.querySelector('#result').textContent = JSON.stringify({ longText, staticOnly, attachmentTag, messageReference, outcome })
} catch (error) {
  document.querySelector('#result').textContent = JSON.stringify({ error: String(error), stack: error.stack })
}
`
let server
try {
  server = await createServer({ configFile: 'vite.config.core-app.ts', server: { host: '127.0.0.1', port: 0 }, plugins: [{ name: 'composer-bounds', resolveId(id) { if (id === '/__bounds_entry.js') return '\0composer-bounds' }, load(id) { if (id === '\0composer-bounds') return entry }, configureServer(s) {
    s.middlewares.use((req, res, next) => {
      if (req.url === '/__composer_bounds') { res.setHeader('Content-Type', 'text/html'); res.end(page) }
      else next()
    })
  } }] })
  await server.listen()
  const { stdout } = await promisify(execFile)(process.env.LAMTOOLS_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', ['--headless', '--disable-gpu', '--no-first-run', '--window-size=1400,900', `--user-data-dir=${join(directory, 'profile')}`, '--virtual-time-budget=15000', '--dump-dom', server.resolvedUrls.local[0] + '__composer_bounds'], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, windowsHide: true, timeout: 60000 })
  const result = stdout.match(/<pre id="result">(.*?)<\/pre>/s)?.[1]
  assert.ok(result && result !== 'loading', `Fixture did not finish: ${result}`)
  const data = JSON.parse(result.replaceAll('&quot;', '"').replaceAll('&amp;', '&'))
  assert.ok(!data.error, JSON.stringify(data))

  // 长文粘贴：即使主题样式失效，内联限高也让编辑区停在 8 行，多余内容在框内滚动。
  assert.ok(data.longText.scrollerHeight <= data.longText.eightLineCap + 1, JSON.stringify(data.longText))
  assert.ok(data.longText.scrollerScrollHeight > data.longText.scrollerHeight, JSON.stringify(data.longText))

  // 第二层兜底：内联样式也失效时，静态样式表仍然把高度限制在 8 行。
  assert.ok(data.staticOnly.scrollerHeight <= data.longText.eightLineCap + 1, JSON.stringify(data.staticOnly))
  assert.ok(data.staticOnly.scrollerScrollHeight > data.staticOnly.scrollerHeight, JSON.stringify(data.staticOnly))

  // 附件标签：宽度限制在 32–64px，长文件名显示省略号，完整名称留在 title 里。
  assert.ok(data.attachmentTag, 'attachment tag was not rendered')
  assert.ok(data.attachmentTag.width >= 32 - 0.5 && data.attachmentTag.width <= 64 + 0.5, JSON.stringify(data.attachmentTag))
  assert.equal(data.attachmentTag.textOverflow, 'ellipsis')
  assert.equal(data.attachmentTag.whiteSpace, 'nowrap')
  assert.equal(data.attachmentTag.overflow, 'hidden')
  assert.ok(data.attachmentTag.title.includes('extremely-long-attachment-file-name'), JSON.stringify(data.attachmentTag))
  // user:“把那个@的符号去掉 换成对应的文件图标”+(标签只显示文件类型徽标 + 文件名)。
  assert.equal(data.attachmentTag.badgeLabel, 'IMG', JSON.stringify(data.attachmentTag))
  assert.equal(data.attachmentTag.badgeRadius, '30%', JSON.stringify(data.attachmentTag))
  assert.ok(data.attachmentTag.badgeContent.includes('IMG'), JSON.stringify(data.attachmentTag))
  assert.ok(!data.attachmentTag.tokenText.includes('@'), JSON.stringify(data.attachmentTag))
  // 消息正文里的 @ 引用同样只显示徽标 + 文件名，徽标 30% 圆角。
  assert.ok(!data.messageReference.text.includes('@'), JSON.stringify(data.messageReference))
  assert.deepEqual(data.messageReference.labels, ['TS', 'MD'], JSON.stringify(data.messageReference))
  assert.equal(data.messageReference.radius, '30%', JSON.stringify(data.messageReference))
  assert.ok(data.messageReference.content.includes('TS'), JSON.stringify(data.messageReference))

  // 成果文件列表：默认 6 个，展开后 8 个，再收起回到 6 个；徽标同样是 30% 圆角。
  assert.equal(data.outcome.initial, 6, JSON.stringify(data.outcome))
  assert.ok(data.outcome.toggle.includes('2'), JSON.stringify(data.outcome))
  assert.equal(data.outcome.badges, 6, JSON.stringify(data.outcome))
  assert.equal(data.outcome.radius, '30%', JSON.stringify(data.outcome))
  assert.equal(data.outcome.expanded, 8, JSON.stringify(data.outcome))
  assert.ok(data.outcome.expandedLabel.includes('收起'), JSON.stringify(data.outcome))
  assert.equal(data.outcome.collapsedAgain, 6, JSON.stringify(data.outcome))

  console.log('PASS: long text caps at 8 lines, file tags stay 32–64px, badges are 30%-rounded without @, and outcome files collapse to six.')
} finally {
  await server?.close()
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
