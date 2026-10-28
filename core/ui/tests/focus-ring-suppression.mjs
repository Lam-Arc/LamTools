// user:“我说取消掉”“统一关闭掉”+(可编辑区域获得焦点时不能出现系统画的黑色焦点框：主聊天、分屏辅助会话和普通可编辑区域统一不显示焦点框)。
import { createServer } from 'vite'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import assert from 'node:assert/strict'
const directory = mkdtempSync(join(tmpdir(), 'lam-focus-ring-'))
const page = `<!doctype html><meta charset="utf-8"><div id="app"></div><pre id="result">loading</pre><script type="module" src="/__focus_ring_entry.js"></script>`
const entry = `
import { createApp, h, ref, nextTick } from 'vue'
import ComposerBar from '/src/components/ComposerBar.vue'
import Editor from '/src/components/InlineFileComposer.vue'
import '/src/styles/variables.css'; import '/src/styles/base.css'; import '/src/styles/layout.css'; import '/src/styles/auxiliary-chat.css';
const draft = ref('')
createApp({ setup(){ return () => h('div', { class: 'workspace-shell workspace-shell--split', style: 'width:760px;padding:24px' }, [
  h(ComposerBar, { modelValue: draft.value, 'onUpdate:modelValue': value => draft.value = value, variant: 'embedded' }, {
    textarea: () => h(Editor, { modelValue: draft.value, 'onUpdate:modelValue': value => draft.value = value, placeholder: '给 Sunday 发送任务...' }),
  }),
  h('div', { id: 'plain-editable', contenteditable: 'true', style: 'margin-top:16px;font:15px/1.45 sans-serif' }, '普通可编辑区域'),
  h('textarea', { id: 'plain-textarea', placeholder: '普通多行输入', style: 'display:block;width:100%;margin-top:16px' }),
  h('div', { id: 'role-textbox', role: 'textbox', tabindex: '0', style: 'margin-top:16px' }, '角色输入框'),
]) } }).mount('#app')
const wait = () => new Promise(resolve => setTimeout(resolve, 30))
const ringOf = element => {
  const style = getComputedStyle(element)
  const width = Number.parseFloat(style.outlineWidth) || 0
  return style.outlineStyle !== 'none' && width > 0 ? { style: style.outlineStyle, width: style.outlineWidth, color: style.outlineColor } : null
}
// 焦点框可能画在获得焦点的元素本身，也可能画在祖先上，所以整条链都要检查。
const ringsInChain = element => {
  const rings = []
  for (let node = element; node && node !== document.body; node = node.parentElement) {
    const ring = ringOf(node)
    if (ring) rings.push({ node: node.className || node.tagName, ...ring })
  }
  return rings
}
// 只聚焦真正可聚焦的输入面；CodeMirror 的外层容器不可聚焦，但它们在编辑器祖先链里，一并检查。
const probes = []
for (const [name, selector] of [['composer editor', '.cm-content'], ['plain contenteditable', '#plain-editable'], ['plain textarea', '#plain-textarea'], ['role textbox', '#role-textbox']]) {
  const element = document.querySelector(selector)
  element.focus(); await wait()
  probes.push({ name, active: document.activeElement === element, rings: ringsInChain(element) })
}
// 对照：阴影根里的可编辑区域不接收文档样式，必须仍显示系统焦点框，用来证明这套检查确实能看见原生焦点框。
const host = document.createElement('div')
document.body.appendChild(host)
const inner = document.createElement('div')
inner.contentEditable = 'true'
inner.textContent = '对照'
inner.style.cssText = 'font:15px/1.45 sans-serif'
host.attachShadow({ mode: 'open' }).appendChild(inner)
inner.focus(); await wait()
const control = { ring: ringOf(inner) }
document.querySelector('#result').textContent = JSON.stringify({ probes, control })
`
let server
try {
  server = await createServer({ configFile: 'vite.config.core-app.ts', server: { host: '127.0.0.1', port: 0 }, plugins: [{ name: 'focus-ring-check', resolveId(id) { if (id === '/__focus_ring_entry.js') return '\0focus-ring-check' }, load(id) { if (id === '\0focus-ring-check') return entry }, configureServer(s) {
    s.middlewares.use((req, res, next) => {
      if (req.url === '/__focus_ring_check') { res.setHeader('Content-Type', 'text/html'); res.end(page) }
      else next()
    })
  } }] })
  await server.listen()
  const { stdout } = await promisify(execFile)(process.env.LAMTOOLS_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', ['--headless', '--disable-gpu', '--no-first-run', '--window-size=1400,900', `--user-data-dir=${join(directory, 'profile')}`, '--virtual-time-budget=15000', '--dump-dom', server.resolvedUrls.local[0] + '__focus_ring_check'], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, windowsHide: true, timeout: 60000 })
  const result = stdout.match(/<pre id="result">(.*?)<\/pre>/s)?.[1]
  assert.ok(result && result !== 'loading', `Fixture did not finish: ${result}`)
  const { probes, control } = JSON.parse(result.replaceAll('&quot;', '"').replaceAll('&amp;', '&'))
  assert.ok(Array.isArray(probes) && probes.length === 4, JSON.stringify(probes))
  assert.ok(control.ring, 'The control surface must show the native focus ring, otherwise this check cannot see one')
  for (const probe of probes) {
    assert.ok(probe.active, `${probe.name} did not take focus`)
    assert.deepEqual(probe.rings, [], `${probe.name} shows a focus ring: ${JSON.stringify(probe.rings)}`)
  }
  console.log('PASS: composer, split auxiliary composer and plain editable surfaces show no native focus ring; the shadow-root control still shows one.')
} finally {
  await server?.close()
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
