import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer } from 'vite'

// user:“分屏布局下，消息流尾部区域会低于输入框上沿，导致尾部消息被遮挡”+(测量真实工作区和输入栏的边界)。
const entry = `
import { createApp, h, ref } from 'vue'
import WorkspaceShell from '/src/components/WorkspaceShell.vue'
import CoreWorkspace from '/src/components/CoreWorkspace.vue'
import { useWorkspace } from '/src/workspace/useWorkspace.ts'
import '/src/styles/variables.css'
import '/src/styles/base.css'
import '/src/styles/layout.css'
import '/src/styles/split-workspace.css'

const edge = new URLSearchParams(location.search).get('edge')
const workspace = useWorkspace(ref('test'), undefined, undefined, { persist: false })
workspace.split('main', edge)
const geometry = ref({})
const editorHeight = ref(36)
window.growComposer = () => { editorHeight.value = 140 }
createApp({
  setup: () => () => h(WorkspaceShell, {
    platform: 'desktop',
    productName: 'Sunday',
    class: 'workspace-shell--split',
    style: geometry.value,
  }, {
    'main-content': () => h('section', { class: 'thread' },
      Array.from({ length: 36 }, (_, index) => h('p', { 'data-message': index }, 'Message ' + index))),
    'composer-textarea': () => h('textarea', { style: { height: editorHeight.value + 'px' } }),
    modals: () => h(CoreWorkspace, {
      controller: workspace, workRoot: '', onGeometry: style => { geometry.value = style },
    }),
  }),
}).mount('#app')
`
const server = await createServer({
  root: fileURLToPath(new URL('../', import.meta.url)),
  configFile: fileURLToPath(new URL('../vite.config.core-app.ts', import.meta.url)),
  server: { host: '127.0.0.1', port: 0 },
  plugins: [{
    name: 'split-thread-tail-fixture',
    resolveId: id => id === '/__split_tail_entry.js' ? '\0split-tail' : null,
    load: id => id === '\0split-tail' ? entry : null,
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (!request.url.startsWith('/__split_tail?')) return next()
        response.setHeader('Content-Type', 'text/html')
        response.end('<!doctype html><meta charset="utf-8"><div id="app"></div><script type="module" src="/__split_tail_entry.js"></script>')
      })
    },
  }],
})

let browser
try {
  await server.listen()
  browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
  for (const edge of ['right', 'bottom', 'top']) {
    await page.goto(server.resolvedUrls.local[0] + '__split_tail?edge=' + edge)
    await page.waitForFunction(() => {
      const shell = document.querySelector('.workspace-shell')
      return shell?.style.getPropertyValue('--split-primary-height') &&
        Number.parseInt(shell.style.getPropertyValue('--composer-height')) ===
          Math.ceil(document.querySelector('.floating-composer').getBoundingClientRect().height)
    })
    for (const size of ['initial', 'expanded']) {
      if (size === 'expanded') {
        await page.evaluate(() => window.growComposer())
        await page.waitForFunction(() => {
          const height = document.querySelector('.floating-composer').getBoundingClientRect().height
          const measured = document.querySelector('.workspace-shell').style.getPropertyValue('--composer-height')
          return height >= 140 && Number.parseInt(measured) === Math.ceil(height)
        })
      }
      const rects = await page.evaluate(() => {
        const thread = document.querySelector('.thread')
        thread.scrollTop = thread.scrollHeight
        return {
          threadBottom: thread.getBoundingClientRect().bottom,
          messageBottom: document.querySelector('[data-message="35"]').getBoundingClientRect().bottom,
          composerTop: document.querySelector('.floating-composer').getBoundingClientRect().top,
          composerBottom: document.querySelector('.floating-composer').getBoundingClientRect().bottom,
          mainBottom: document.querySelector('.workspace-main').getBoundingClientRect().bottom,
        }
      })
      assert.ok(rects.composerBottom <= rects.mainBottom, `${edge} ${size}: composer outside main pane ${JSON.stringify(rects)}`)
      assert.ok(rects.threadBottom <= rects.composerTop + 1, `${edge} ${size}: thread under composer ${JSON.stringify(rects)}`)
      assert.ok(rects.messageBottom <= rects.threadBottom, `${edge} ${size}: last message is clipped ${JSON.stringify(rects)}`)
    }
  }
  console.log('Messages stay above the composer in side-by-side and stacked splits as it grows.')
} finally {
  await browser?.close()
  await server.close()
}
