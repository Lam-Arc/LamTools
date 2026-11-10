/**
 * Ping 框选工具回归验收。
 *
 * user:“重新设计与实现 Ping 的框选工具……任何步骤按 Esc 都可以安全退出；
 * 即使发生异常，也必须存在可靠的恢复办法”+
 * (旧实现用 Ping 覆盖层吃整屏鼠标，无法聚焦、Esc 失效、卡住后只能杀进程。
 *  这里从三层锁住新实现：几何计算、宿主窗口/看门狗、前端退出与发送。)
 */
import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  cropFor,
  displayRectFor,
  frameToClient,
  normalizeRegion,
  pointToFrame,
  regionToFrame,
  selectionMeta,
} from '../src/pet/capture/geometry.ts'

const uiRoot = resolve(import.meta.dirname, '../src')
const desktopRoot = resolve(import.meta.dirname, '../../desktop')
const tauriRoot = resolve(desktopRoot, 'src-tauri')
const petMod = readFileSync(resolve(tauriRoot, 'src/pet/mod.rs'), 'utf8')
const mainRs = readFileSync(resolve(tauriRoot, 'src/main.rs'), 'utf8')
const platform = readFileSync(resolve(tauriRoot, 'src/pet/platform.rs'), 'utf8')

/** 只取某个函数/命令的源码段，避免全文件匹配误伤别的命令。 */
function section(source: string, marker: string, endMarker: string): string {
  const start = source.indexOf(marker)
  expect(start, `${marker} 必须存在`).toBeGreaterThanOrEqual(0)
  const end = source.indexOf(endMarker, start + marker.length)
  return end < 0 ? source.slice(start) : source.slice(start, end)
}

describe('截图几何：多屏 / DPI / 反向拖拽', () => {
  // user:“必须保证多显示器、不同缩放比例下选框位置正确”+
  // (截图是物理像素，窗口是 CSS 像素，中间差一个显示器缩放。)
  it('等比铺满窗口并居中（上下或左右留黑边）', () => {
    const rect = displayRectFor(2000, 1000, 1000, 1000)
    expect(rect.scale).toBe(0.5)
    expect(rect.width).toBe(1000)
    expect(rect.height).toBe(500)
    expect(rect.offsetX).toBe(0)
    expect(rect.offsetY).toBe(250)
  })

  it('窗口与截图比例一致时无偏移（截图窗口按显示器物理尺寸创建）', () => {
    const rect = displayRectFor(2560, 1440, 1280, 720)
    expect(rect.scale).toBe(0.5)
    expect(rect.offsetX).toBe(0)
    expect(rect.offsetY).toBe(0)
  })

  it('反向拖拽得到正矩形', () => {
    expect(normalizeRegion({ x1: 120, y1: 90, x2: 20, y2: 10 })).toEqual({
      x: 20,
      y: 10,
      width: 100,
      height: 80,
    })
  })

  it('过小的框选视为没有框选', () => {
    expect(normalizeRegion({ x1: 0, y1: 0, x2: 3, y2: 3 })).toBeNull()
    expect(normalizeRegion(null)).toBeNull()
  })

  it('窗口坐标换算截图像素时扣除黑边并夹在边界内', () => {
    const rect = displayRectFor(2000, 1000, 1000, 1000)
    expect(pointToFrame(500, 500, 2000, 1000, rect)).toEqual({ x: 1000, y: 500 })
    expect(pointToFrame(-100, -100, 2000, 1000, rect)).toEqual({ x: 0, y: 0 })
    expect(pointToFrame(5000, 5000, 2000, 1000, rect)).toEqual({ x: 2000, y: 1000 })
  })

  it('文字块定位与点击位置可逆', () => {
    const rect = displayRectFor(2560, 1440, 1280, 720)
    const client = frameToClient(640, 360, rect)
    expect(client).toEqual({ left: 320, top: 180 })
    expect(pointToFrame(client.left, client.top, 2560, 1440, rect)).toEqual({ x: 640, y: 360 })
  })

  it('没有框选时发送整屏', () => {
    expect(cropFor(null, 1920, 1080)).toEqual({ x: 0, y: 0, width: 1920, height: 1080 })
  })

  it('导出位置叠加显示器原点与缩放（负坐标副屏也正确）', () => {
    const meta = selectionMeta(
      { x: -1920, y: -200, scale: 1.25 },
      { x: 100, y: 50, width: 400, height: 300 },
    )
    expect(meta).toEqual({ x: -1820, y: -150, width: 400, height: 300, scale: 1.25 })
  })
})

describe('截图窗口：独立、可聚焦、可回收', () => {
  // user:“框选工具……冻结桌面、无法点击、Esc 不生效”+
  // (截图窗口是普通可激活窗口，不再复用 WS_EX_NOACTIVATE 的 Ping 覆盖层。)
  it('创建独立的 ping-capture 窗口并加载 capture.html', () => {
    expect(petMod).toContain('pub const PING_CAPTURE_LABEL: &str = "ping-capture"')
    const open = section(petMod, 'pub async fn pet_ping_capture_open', 'pub async fn pet_ping_capture_frame')
    expect(open).toContain('PING_CAPTURE_LABEL')
    expect(open).toContain('capture.html')
    expect(open).toContain('.decorations(false)')
    expect(open).toContain('.always_on_top(true)')
    expect(open).toContain('place_overlay')
    expect(open).toContain('set_focus')
    // 覆盖层的不可激活样式不能套到截图窗口上，否则 Esc / 输入框照样收不到。
    expect(open).not.toContain('configure_overlay_window')
  })

  it('打开前清空上一轮状态，不允许重入叠加', () => {
    const reset = section(petMod, 'fn reset_capture_window', '/// 看门狗')
    expect(reset).toContain('capture_gen.fetch_add')
    expect(reset).toContain('capture_frame')
    expect(reset).toContain('capture_heartbeat')
    expect(reset).toContain('window.destroy()')
    const open = section(petMod, 'pub async fn pet_ping_capture_open', 'pub async fn pet_ping_capture_frame')
    expect(open.indexOf('reset_capture_window')).toBeLessThan(open.indexOf('capture_with_overlay_hidden'))
  })

  it('截图前把 Ping 覆盖层退回穿透并清空命中区', () => {
    const park = section(petMod, 'fn park_ping_overlay', 'fn reset_capture_window')
    expect(park).toContain('set_ignore_cursor_events(true)')
    expect(park).toContain('ping_interactive')
    expect(park).toContain('rects.clear()')
    expect(park).toContain('"auto"')
    expect(park).toContain('set_overlay_activatable(&window, false)')
  })

  it('多显示器下按鼠标所在显示器截图并使用其原点/缩放', () => {
    const open = section(petMod, 'pub async fn pet_ping_capture_open', 'pub async fn pet_ping_capture_frame')
    expect(open).toContain('cursor_position')
    expect(open).toContain('monitor_at')
    expect(open).toContain('encode_capture_bytes(')
    expect(open).toContain('monitor.x')
    expect(open).toContain('monitor.scale')
  })

  it('看门狗用心跳超时 + 系统无响应判定，并原生隐藏窗口', () => {
    const watchdog = section(petMod, 'fn start_capture_watchdog', 'pub async fn pet_ping_capture_open')
    expect(watchdog).toContain('CAPTURE_HEARTBEAT_TIMEOUT')
    expect(watchdog).toContain('is_window_hung')
    expect(watchdog).toContain('emergency_hide_window')
    expect(watchdog).toContain('capture_gen.load')
    // 恢复与正常退出复用同一套清理（清帧、心跳、代次）。
    expect(watchdog).toContain('reset_capture_window')
    expect(watchdog).toContain('capture-recovered')
    // user:“任何步骤按 Esc 都可以安全退出”+(窗口刚打开、WebView 还没拿到键盘焦点时，
    // 原生轮询也要能关掉；不能依赖页面 keydown。)
    expect(watchdog).toContain('escape_down')
    expect(watchdog).toContain('native fallback')
  })

  it('平台层提供 IsHungAppWindow / ShowWindow(SW_HIDE) 并可从任意线程调用', () => {
    const esc = section(platform, 'pub fn escape_down', '/// 截图窗口是否已被系统判定为无响应')
    expect(esc).toContain('GetAsyncKeyState')
    expect(esc).toContain('0x1B')
    const hung = section(platform, 'pub fn is_window_hung', '/// 看门狗线程')
    expect(hung).toContain('IsHungAppWindow')
    const hide = section(platform, 'pub fn emergency_hide_window', '/// 框选/标注需要键盘')
    expect(hide).toContain('ShowWindow')
    expect(hide).toContain('SW_HIDE')
    expect(hide).toContain('HWND_NOTOPMOST')
  })

  it('退出路径统一为 close：销毁窗口、清空帧和心跳、发关闭事件', () => {
    const close = section(petMod, 'pub async fn pet_ping_capture_close', '// 命令：全局 Ping 快捷键')
    expect(close).toContain('reset_capture_window')
    expect(close).toContain('capture-closed')
  })

  it('隔离测试入口能冻结心跳，验证看门狗真实生效', () => {
    expect(petMod).toContain('simulate_capture_heartbeat_stall')
    expect(petMod).toContain('capture_heartbeat_frozen')
    const heartbeat = section(petMod, 'pub fn pet_ping_capture_heartbeat', '/// 隔离测试')
    expect(heartbeat).toContain('capture_heartbeat_frozen')
    expect(mainRs).toContain('--capture-freeze-heartbeat')
    // 每次 open/close 复位冻结标志，正常使用不受测试入口影响。
    const reset = section(petMod, 'fn reset_capture_window', '/// 看门狗')
    expect(reset).toContain('capture_heartbeat_frozen')
    expect(reset).toContain('store(false')
  })

  it('命令注册与窗口能力齐全', () => {
    for (const command of [
      'pet_ping_capture_open',
      'pet_ping_capture_frame',
      'pet_ping_capture_show',
      'pet_ping_capture_heartbeat',
      'pet_ping_capture_close',
    ]) {
      expect(mainRs).toContain(`pet::${command}`)
    }
    const conf = JSON.parse(readFileSync(resolve(tauriRoot, 'tauri.conf.json'), 'utf8'))
    const capability = conf.app.security.capabilities.find(
      (item: { identifier: string }) => item.identifier === 'default',
    )
    expect(capability.windows).toContain('ping-capture')
  })

  it('截图窗口有独立入口页与构建入口', () => {
    const html = readFileSync(resolve(desktopRoot, 'capture.html'), 'utf8')
    expect(html).toContain('capture.ts')
    expect(html).toContain('capture-app')
    const vite = readFileSync(resolve(desktopRoot, 'vite.config.ts'), 'utf8')
    expect(vite).toContain("capture: resolve(__dirname, 'capture.html')")
    expect(existsSync(resolve(desktopRoot, 'src/capture.ts'))).toBe(true)
  })
})

describe('前端：退出、发送与旧的整屏标注路径', () => {
  it('旧的 PingAnnotator 已移除，PingSurface 通过独立窗口打开框选', () => {
    expect(existsSync(resolve(uiRoot, 'pet/ui/PingAnnotator.vue'))).toBe(false)
    const surface = readFileSync(resolve(uiRoot, 'pet/ui/PingSurface.vue'), 'utf8')
    expect(surface).not.toContain('PingAnnotator')
    expect(surface).toContain('openCapture')
    expect(surface).toContain('openPingCapture')
  })

  it('「框选」扇区只调用独立窗口入口，不再设置整屏标注请求', () => {
    const runtime = readFileSync(resolve(uiRoot, 'pet/ping/usePingRuntime.ts'), 'utf8')
    expect(runtime).not.toContain('selectionRequest')
    const branch = section(runtime, "if (sector.kind === 'select')", 'if (sector.kind === \'subring\')')
    expect(branch).toContain('cancelRing()')
    expect(branch).toContain('deps.openCapture')
    expect(branch).not.toContain('setPingInputMode')
  })

  it('bridge 暴露完整的截图窗口命令', () => {
    const bridge = readFileSync(resolve(uiRoot, 'pet/bridge.ts'), 'utf8')
    for (const command of [
      'pet_ping_capture_open',
      'pet_ping_capture_frame',
      'pet_ping_capture_show',
      'pet_ping_capture_heartbeat',
      'pet_ping_capture_close',
    ]) {
      expect(bridge).toContain(command)
    }
    expect(bridge).toContain('export function decodeCapturedFrame')
  })

  it('Esc / 取消 / 发送完成都走同一个 close', () => {
    const app = readFileSync(resolve(uiRoot, 'pet/ui/CaptureApp.vue'), 'utf8')
    expect(app).toContain("event.key !== 'Escape'")
    expect(app).toContain('closePingCapture')
    expect(app).toContain('@cancel="cancel"')
    // 发送成功 → 打开主窗口 → 关闭截图窗口。
    const send = section(app, 'async function send', 'onMounted')
    expect(send.indexOf('openMainSession')).toBeLessThan(send.indexOf('closePingCapture'))
  })

  it('页面持续心跳，避免看门狗误收窗口', () => {
    const app = readFileSync(resolve(uiRoot, 'pet/ui/CaptureApp.vue'), 'utf8')
    expect(app).toContain('heartbeatPingCapture')
    expect(app).toMatch(/setInterval\([\s\S]*?800/)
  })

  it('发送复用 Ping 通道：活动回合是引导，不排队', () => {
    const app = readFileSync(resolve(uiRoot, 'pet/ui/CaptureApp.vue'), 'utf8')
    expect(app).toContain('pingTarget()')
    expect(app).toContain('channel.send')
    expect(app).toContain("result.status === 'ignored'")
    expect(app).not.toContain('steerTurn(')
  })

  it('标注工具齐全且不使用阻塞式 prompt（会停掉心跳）', () => {
    const editor = readFileSync(resolve(uiRoot, 'pet/ui/CaptureEditor.vue'), 'utf8')
    for (const tool of ['question', 'exclamation', 'arrow', 'text', 'pen', 'region']) {
      expect(editor).toContain(`'${tool}'`)
    }
    expect(editor).toContain('undo')
    expect(editor).toContain('redo')
    expect(editor).toContain('clearAll')
    expect(editor).not.toContain('window.prompt')
    expect(editor).toContain('textDraft')
  })

  it('工具条按内容自适应，输入栏比工具条左右各宽 32px', () => {
    const editor = readFileSync(resolve(uiRoot, 'pet/ui/CaptureEditor.vue'), 'utf8')
    expect(editor).toContain('toolsBar')
    expect(editor).toContain('ResizeObserver')
    expect(editor).toContain('INPUT_SIDE_GUTTER')
    expect(editor).toContain('INPUT_SIDE_GUTTER * 2')
    expect(editor).toContain('inputWidth')
    // 输入栏不再按文字长度收缩，否则会比上面的工具条还短。
    expect(editor).not.toContain('capture__measure')
    expect(editor).not.toContain('width: min(620px')
  })

  it('导出使用选区和共享几何计算，元数据带屏幕原点', () => {
    const editor = readFileSync(resolve(uiRoot, 'pet/ui/CaptureEditor.vue'), 'utf8')
    expect(editor).toContain('cropFor(')
    expect(editor).toContain('selectionMeta(')
    expect(editor).toContain("output.toBlob(resolve, 'image/png')")
  })

  it('页面挂载前的 Esc 兜底也能关闭窗口', () => {
    const entry = readFileSync(resolve(desktopRoot, 'src/capture.ts'), 'utf8')
    expect(entry).toContain("event.key !== 'Escape'")
    expect(entry).toContain('closePingCapture')
    expect(entry).toContain('childElementCount')
  })

  it('截图窗口源码足够小，不含旧的整屏覆盖层逻辑', () => {
    const app = readFileSync(resolve(uiRoot, 'pet/ui/CaptureApp.vue'), 'utf8')
    expect(app).not.toContain('setPingInputMode')
    expect(app).not.toContain('selectionRequest')
    for (const relative of ['pet/capture/geometry.ts', 'pet/ui/CaptureEditor.vue', 'pet/ui/CaptureApp.vue']) {
      expect(statSync(resolve(uiRoot, relative)).size).toBeGreaterThan(200)
    }
  })
})

describe('标注层圈选 → 截图选区', () => {
  // user:“合并，这样更干净”+(圈选直接进截图编辑器，选区必须按截图原点换算，
  // 否则副屏负坐标或 DPI 缩放会让预置选框整体偏移)。
  const frame = { x: 100, y: 50, width: 800, height: 600 }

  it('按截图原点换算成截图内像素', () => {
    expect(regionToFrame([200, 150, 300, 200], frame)).toEqual({
      x1: 100,
      y1: 100,
      x2: 400,
      y2: 300,
    })
  })

  it('超出截图范围的部分被裁掉', () => {
    expect(regionToFrame([0, 0, 2000, 2000], frame)).toEqual({
      x1: 0,
      y1: 0,
      x2: 800,
      y2: 600,
    })
  })

  it('区域完全不在截图内时返回 null', () => {
    expect(regionToFrame([2000, 2000, 100, 100], frame)).toBeNull()
  })

  it('太小的选区返回 null，保持整屏发送', () => {
    expect(regionToFrame([200, 150, 3, 3], frame)).toBeNull()
  })
})
