// user:“让左侧栏和主内容区中间的边界可以被拖动”“把左侧栏默认给的位置大一点…15%吧”
// user:“把“新建会话”按钮放在项目最右侧，它的左侧是“三个点更多”按钮”
// +(用本地浏览器引擎量真实布局：默认档位比原来宽 15%，拖分界线能改宽度且聊天区跟着让位，
//   双击回默认；项目行最右是新建会话图标，「···」紧贴它左侧。)
import { createServer } from 'vite'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import assert from 'node:assert/strict'

const directory = mkdtempSync(join(tmpdir(), 'lam-sidebar-divider-'))
const page = `<!doctype html><meta charset="utf-8"><div id="app"></div><pre id="result">loading</pre><script type="module" src="/__divider_entry.js"></script>`
const entry = `
import { createApp, h, nextTick } from 'vue'
import WorkspaceShell from '/src/components/WorkspaceShell.vue'
import SessionSidebar from '/src/components/SessionSidebar.vue'
import '/src/styles/variables.css'
import '/src/styles/base.css'
import '/src/styles/layout.css'

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const box = (element) => {
  const rect = element?.getBoundingClientRect()
  return rect ? { left: rect.left, right: rect.right, width: rect.width, top: rect.top, height: rect.height } : null
}

const groups = [
  { id: 'docs', name: 'Docs', sessions: [{ id: 's1', title: 'Guide' }] },
  { id: 'lab', name: 'Lab', sessions: [{ id: 's2', title: 'Notes' }] },
]

const app = createApp({
  render: () => h(WorkspaceShell, {
    productName: 'Sunday',
    storageKey: 'layout-divider-check',
    sidebarTitle: '项目',
    showRightPanel: false,
  }, {
    'sidebar-body': () => h(SessionSidebar, {
      projectGroups: groups,
      allowProjectNewSession: true,
    }),
  }),
})
app.mount('#app')

try {
  await nextTick()
  await wait(120)

  const shell = document.querySelector('.workspace-shell')
  const handle = document.querySelector('[data-sidebar-resize-handle]')
  const row = document.querySelector('[data-project-row="docs"]')
  const newSession = row?.querySelector('[data-project-new-session="docs"]')
  const menuTrigger = row?.querySelector('[data-project-menu-trigger="docs"]')

  const measure = () => {
    const drawer = document.querySelector('[data-workspace-left-drawer]')
    const main = document.querySelector('.workspace-main')
    return {
      drawer: box(drawer),
      main: box(main),
      handle: box(handle),
      handleDisplay: handle ? getComputedStyle(handle).display : null,
      handleCursor: handle ? getComputedStyle(handle).cursor : null,
      handleSeparator: handle?.getAttribute('role') ?? null,
      row: box(row),
      name: box(row?.querySelector('[data-project-entry="docs"]')),
      menu: box(menuTrigger),
      newSession: box(newSession),
      newSessionIsLast: row?.lastElementChild === newSession,
      newSessionIcon: (() => {
        const svg = newSession?.querySelector('svg')
        if (!svg) return null
        const iconBox = svg.getBoundingClientRect()
        return {
          width: iconBox.width,
          height: iconBox.height,
          viewBox: svg.getAttribute('viewBox'),
          shapes: svg.querySelectorAll('path,circle,rect,line').length,
        }
      })(),
      menuParentIsPrevious: newSession?.previousElementSibling === menuTrigger?.parentElement,
      rowClass: row?.className ?? '',
      sidebarVar: shell ? getComputedStyle(shell).getPropertyValue('--sidebar-width').trim() : null,
      bodyClass: document.body.className,
      stored: localStorage.getItem('layout-divider-check'),
    }
  }

  const initial = measure()
  let pressed = null
  let dragged = null
  let released = null
  let reset = null

  if (handle) {
    const rect = handle.getBoundingClientRect()
    const startX = Math.round(rect.left + rect.width / 2)
    const pointerY = Math.round(rect.top + 160)
    const pointer = (type, clientX) => new PointerEvent(type, {
      bubbles: true,
      cancelable: true,
      clientX,
      clientY: pointerY,
      pointerId: 1,
      pointerType: 'mouse',
      button: 0,
      buttons: type === 'pointerup' ? 0 : 1,
    })

    handle.dispatchEvent(pointer('pointerdown', startX))
    await nextTick()
    await wait(80)
    pressed = measure()

    window.dispatchEvent(pointer('pointermove', startX + 60))
    await nextTick()
    await wait(80)
    dragged = measure()

    window.dispatchEvent(pointer('pointerup', startX + 60))
    await nextTick()
    await wait(700)
    released = measure()

    handle.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
    await nextTick()
    await wait(120)
    reset = measure()
  }

  const result = { initial, pressed, dragged, released, reset }
  document.querySelector('#result').textContent = JSON.stringify(result)
} catch (error) {
  document.querySelector('#result').textContent = JSON.stringify({ error: String(error), stack: error.stack })
}
`

function assertProjectRow(state, iconSize) {
  assert.ok(state.newSessionIcon, 'the new-session icon is missing')
  assert.ok(
    Math.abs(state.newSessionIcon.width - iconSize) <= 0.5
      && Math.abs(state.newSessionIcon.height - iconSize) <= 0.5,
    `new-session icon should render at ${iconSize}px: ${JSON.stringify(state.newSessionIcon)}`,
  )
  assert.ok(state.newSessionIcon.shapes >= 2, JSON.stringify(state.newSessionIcon))
  assert.ok(state.newSessionIsLast, JSON.stringify(state.rowClass))
  assert.ok(state.menuParentIsPrevious, 'the menu cluster must sit right before the new-session button')
  assert.ok(state.rowClass.includes('has-project-new-session'), JSON.stringify(state.rowClass))
  assert.ok(
    Math.abs(state.row.right - state.newSession.right) <= 1,
    JSON.stringify({ row: state.row, newSession: state.newSession }),
  )
  assert.ok(
    state.menu.right <= state.newSession.left + 0.5 && state.menu.left > state.name.left,
    JSON.stringify({ menu: state.menu, newSession: state.newSession }),
  )
  assert.ok(
    state.newSession.left - state.menu.right >= 4,
    `menu and new-session need breathing room: ${JSON.stringify({ menu: state.menu, newSession: state.newSession })}`,
  )
}

let server
async function runAt(width, expectedDefault) {
  const { stdout } = await promisify(execFile)(
    process.env.LAMTOOLS_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    [
      '--headless',
      '--disable-gpu',
      '--no-first-run',
      `--window-size=${width},900`,
      `--user-data-dir=${join(directory, `profile-${width}`)}`,
      '--virtual-time-budget=15000',
      '--dump-dom',
      `${server.resolvedUrls.local[0]}__sidebar_divider`,
    ],
    { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, windowsHide: true, timeout: 90000 },
  )
  const raw = stdout.match(/<pre id="result">(.*?)<\/pre>/s)?.[1]
  assert.ok(raw && raw !== 'loading', `fixture did not finish: ${raw}`)
  const data = JSON.parse(raw.replaceAll('&quot;', '"').replaceAll('&amp;', '&'))
  assert.ok(!data.error, JSON.stringify(data))

  const { initial, pressed, dragged, released, reset } = data

  if (expectedDefault === null) {
    // 手机宽度：抽屉是浮层，不参与拖拽；项目行的按钮排布仍要成立。
    assert.equal(initial.handle, null, JSON.stringify(initial.handle))
    assertProjectRow(initial, 18)
    return data
  }

  // 1) 默认档位整体放大 15%：1400 窗口用中间档 230，1000 窗口用紧凑档 186。
  assert.equal(initial.sidebarVar, `${expectedDefault}px`, JSON.stringify(initial))
  assert.ok(Math.abs(initial.drawer.width - expectedDefault) <= 1, JSON.stringify(initial.drawer))

  // 2) 分界线存在、贴着会话栏右缘、可拖。
  assert.ok(initial.handle, 'resize handle is missing')
  assert.notEqual(initial.handleDisplay, 'none', JSON.stringify(initial.handleDisplay))
  assert.equal(initial.handleCursor, 'col-resize', JSON.stringify(initial.handleCursor))
  assert.equal(initial.handleSeparator, 'separator', JSON.stringify(initial.handleSeparator))
  assert.ok(
    Math.abs(initial.handle.left + initial.handle.width / 2 - (initial.drawer.right + 1.5)) <= 3,
    JSON.stringify({ handle: initial.handle, drawer: initial.drawer }),
  )

  // 3) 按下即进入拖拽态；拖 60px 后会话栏变宽 60，聊天卡同步让位。
  assert.ok(pressed.bodyClass.includes('sidebar-is-resizing'), JSON.stringify(pressed.bodyClass))
  assert.ok(Math.abs(pressed.drawer.width - expectedDefault) <= 1, JSON.stringify(pressed.drawer))
  assert.ok(Math.abs(dragged.drawer.width - (expectedDefault + 60)) <= 1, JSON.stringify(dragged.drawer))
  assert.ok(
    Math.abs(dragged.main.left - (dragged.drawer.right + 3)) <= 1,
    JSON.stringify({ main: dragged.main, drawer: dragged.drawer }),
  )

  // 4) 松手退出拖拽态并落盘，双击回到默认档。
  assert.ok(!released.bodyClass.includes('sidebar-is-resizing'), JSON.stringify(released.bodyClass))
  assert.equal(JSON.parse(released.stored || '{}').leftWidth, expectedDefault + 60, released.stored)
  assert.ok(Math.abs(reset.drawer.width - expectedDefault) <= 1, JSON.stringify(reset.drawer))
  assert.equal(reset.sidebarVar, `${expectedDefault}px`, JSON.stringify(reset))

  // 5) 项目行：新建会话在最右，三个点紧贴它左侧，行的右缘就是新建图标的右缘。
  assertProjectRow(initial, 15)

  return data
}

try {
  server = await createServer({
    configFile: 'vite.config.core-app.ts',
    server: { host: '127.0.0.1', port: 0 },
    plugins: [{
      name: 'sidebar-divider',
      resolveId(id) {
        if (id === '/__divider_entry.js') return '\0sidebar-divider'
        return null
      },
      load(id) {
        if (id === '\0sidebar-divider') return entry
        return null
      },
      configureServer(s) {
        s.middlewares.use((req, res, next) => {
          if (req.url === '/__sidebar_divider') {
            res.setHeader('Content-Type', 'text/html')
            res.end(page)
          } else {
            next()
          }
        })
      },
    }],
  })
  await server.listen()

  await runAt(1400, 230)
  await runAt(1000, 186)
  await runAt(600, null)

  console.log('PASS: divider drags the sidebar width both ways, default tiers are 15% wider, and the project row ends with the new-session icon right of the menu trigger.')
} finally {
  await server?.close()
  rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
}
