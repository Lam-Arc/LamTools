/**
 * 覆盖层与 Tauri 原生命令的桥接。
 *
 * 所有系统能力都经这里；前端不直接拼路径、不直接碰窗口，便于禁用桌宠时整块摘掉。
 */
import { isRelativeSafePath, type ImportScanResult } from './assets/importer.ts'

export interface OverlayBounds {
  x: number
  y: number
  width: number
  height: number
  scale: number
}

export interface MonitorInfo {
  id: string
  x: number
  y: number
  width: number
  height: number
  primary: boolean
  scale: number
}

export interface CapturedFrame {
  width: number
  height: number
  /** 该显示器左上角在虚拟桌面里的坐标。 */
  x: number
  y: number
  scale: number
  data: Uint8ClampedArray
  capturedAt: number
}

export interface InstalledPack {
  id: string
  dir: string
  files: number
  bytes: number
}

export function isTauriRuntime(): boolean {
  return typeof (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ === 'object'
}

async function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauriRuntime()) throw new Error('桌宠覆盖层需要桌面端运行（Tauri）')
  const module = await import('@tauri-apps/api/core')
  return await module.invoke<T>(command, args)
}

let apiBasePromise: Promise<string> | null = null

export async function apiBase(): Promise<string> {
  if (!apiBasePromise) {
    apiBasePromise = invoke<string>('get_api_base').catch(error => {
      apiBasePromise = null
      throw error
    })
  }
  return await apiBasePromise
}

export async function openOverlay(): Promise<OverlayBounds> {
  return await invoke<OverlayBounds>('pet_overlay_open')
}

export async function closeOverlay(): Promise<void> {
  await invoke('pet_overlay_close')
}

/** 命中矩形：物理像素屏幕坐标 [x, y, w, h]。 */
export async function setInteractiveRects(rects: number[][]): Promise<void> {
  await invoke('pet_set_interactive_rects', { rects })
}

/**
 * Ping 会话卡片 = 独立窗口（原生 Acrylic，与主窗口同一套材质）。
 *
 * user:“卡片即窗口，把 ping 和桌宠拆分开”+(卡片不再画在桌宠覆盖层里，
 * 每张卡片一个自己的窗口，桌宠与 Ping 的卡片面解耦。)
 */
export interface PingCardWindowInput {
  cardId: string
  sessionId: string
  projectId: string | null
  title: string
  /** [x, y, width, height]，屏幕物理像素。 */
  rect: [number, number, number, number]
}

export async function openPingCard(input: PingCardWindowInput): Promise<void> {
  await invoke('pet_open_ping_card', { ...input })
}

export async function showPingCard(cardId: string): Promise<void> {
  await invoke('pet_show_ping_card', { cardId })
}

export async function closePingCard(cardId: string): Promise<void> {
  await invoke('pet_close_ping_card', { cardId })
}

/**
 * Ping 完成后打开 Sunday 本体并切到对应会话。
 *
 * user:“ping完之后用一个合适的大小打开Sunday本体”+(不再开卡片窗口，
 * 直接复用主窗口的聊天与输入界面。)
 */
export async function openMainSession(projectId: string | null, sessionId: string): Promise<void> {
  await invoke('pet_open_main_session', { projectId, sessionId })
}

/**
 * Ping 独立覆盖层（环/标记/标注/会话选择器）。
 *
 * user:“你看看 ping 环 要不也自己做窗口？”+(Ping 有自己的全屏覆盖层窗口，
 * 与桌宠窗口解耦：桌宠禁用或关掉，Ping 入口照常可用。)
 */
export async function openPingOverlay(): Promise<OverlayBounds> {
  return await invoke('pet_ping_overlay_open')
}

export async function showPingOverlay(): Promise<void> {
  await invoke('pet_ping_overlay_show')
}

export async function hidePingOverlay(): Promise<void> {
  await invoke('pet_ping_overlay_hide')
}

export async function setPingInteractiveRects(rects: number[][]): Promise<void> {
  await invoke('pet_ping_set_interactive_rects', { rects })
}

export async function setPingInputMode(mode: 'auto' | 'capture' | 'passthrough'): Promise<void> {
  await invoke('pet_ping_set_input_mode', { mode })
}

/**
 * 独立截图窗口：拍下静态截图并打开专门的框选/标注窗口。
 *
 * user:“重新设计与实现 Ping 的框选工具”+(不再让 Ping 覆盖层吃掉整屏鼠标；
 * 截图窗口可聚焦、可收键盘、可被看门狗强制收起。)
 */
export async function openPingCapture(): Promise<OverlayBounds> {
  return await invoke('pet_ping_capture_open')
}

export async function fetchPingCaptureFrame(): Promise<CapturedFrame> {
  const buffer = await invoke<ArrayBuffer>('pet_ping_capture_frame')
  return decodeCapturedFrame(buffer)
}

export async function showPingCapture(): Promise<void> {
  await invoke('pet_ping_capture_show')
}

export async function heartbeatPingCapture(): Promise<void> {
  await invoke('pet_ping_capture_heartbeat')
}

export async function closePingCapture(): Promise<void> {
  await invoke('pet_ping_capture_close')
}

/**
 * 覆盖层心跳：告诉宿主"这块窗口还有人画"。
 *
 * user:“从你启动开始就一直是黑屏未响应状态”+(宿主侧没人画的全屏窗口必须能被
 * 判死并自动收起，否则用户会被一块盖屏窗口锁在桌面前什么都点不到。)
 */
export async function overlayHeartbeat(): Promise<void> {
  await invoke('pet_overlay_heartbeat')
}

/**
 * 页面画出第一帧后调用：宿主在这之前一直把覆盖层窗口藏着，
 * 这样页面对不了的时候用户只会什么也看不到，而不是被一块黑屏盖住。
 */
export async function overlayReady(): Promise<void> {
  await invoke('pet_overlay_ready')
}

export async function setInputMode(mode: 'auto' | 'capture' | 'passthrough'): Promise<void> {
  await invoke('pet_set_input_mode', { mode })
}

/** 主窗口是否聚焦：聚焦时桌宠不显示气泡（用户已经在主界面里）。 */
export async function mainWindowFocused(): Promise<boolean> {
  return await invoke<boolean>('pet_main_window_focused')
}

export async function setZMode(mode: 'top' | 'behind' | 'clip'): Promise<void> {
  await invoke('pet_set_z_mode', { mode })
}

export async function listMonitors(): Promise<MonitorInfo[]> {
  return await invoke<MonitorInfo[]>('pet_monitors')
}

export async function setPingHotkey(accelerator: string | null): Promise<void> {
  await invoke('pet_hotkey_set', { accelerator })
}

export interface PetDesktopWindow {
  id: string
  title: string
  className: string
  bounds: { x: number; y: number; width: number; height: number }
  z: number
}

/** L2 地形来源：真实桌面窗口（已排除 Sunday 自己的进程）。 */
export async function desktopWindows(): Promise<PetDesktopWindow[]> {
  return await invoke<PetDesktopWindow[]>('pet_desktop_windows')
}

export async function readConfigText(): Promise<string | null> {
  return await invoke<string | null>('pet_config_read')
}

export async function scanImport(path: string): Promise<ImportScanResult> {
  const scan = await invoke<{ root: string; files: { rel: string; size: number; ext: string }[]; total_bytes: number }>(
    'pet_scan_import',
    { path },
  )
  return { root: scan.root, files: scan.files, totalBytes: scan.total_bytes }
}

/** ZIP 导入期间，资源来自内存而不是磁盘。 */
let zipSource: Map<string, Uint8Array> | null = null
let importGeneration = 0

export function setZipImportSource(entries: Map<string, Uint8Array> | null): void {
  zipSource = entries
  importGeneration += 1
  resetAssetCache()
}

export async function readImageFile(path: string): Promise<Uint8Array> {
  const buffer = await invoke<ArrayBuffer>('pet_read_image', { path })
  return new Uint8Array(buffer)
}

export async function readZipFile(path: string): Promise<Uint8Array> {
  const buffer = await invoke<ArrayBuffer>('pet_read_zip', { path })
  return new Uint8Array(buffer)
}

/** 整包二进制写入：一次性传输，避免逐文件 JSON 数组把大模型拖慢。 */
export async function writePackBundle(
  packName: string,
  entries: { rel: string; bytes: Uint8Array }[],
): Promise<InstalledPack> {
  const nameBytes = new TextEncoder().encode(packName)
  const encoder = new TextEncoder()
  const chunks: Uint8Array[] = []
  const header = new Uint8Array(2)
  new DataView(header.buffer).setUint16(0, nameBytes.length, true)
  chunks.push(header, nameBytes)
  const count = new Uint8Array(4)
  new DataView(count.buffer).setUint32(0, entries.length, true)
  chunks.push(count)
  for (const entry of entries) {
    if (!isRelativeSafePath(entry.rel)) throw new Error(`资源路径不安全：${entry.rel}`)
    const relBytes = encoder.encode(entry.rel)
    const relLength = new Uint8Array(2)
    new DataView(relLength.buffer).setUint16(0, relBytes.length, true)
    const dataLength = new Uint8Array(4)
    new DataView(dataLength.buffer).setUint32(0, entry.bytes.byteLength, true)
    chunks.push(relLength, relBytes, dataLength, entry.bytes)
  }
  const total = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0)
  const payload = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    payload.set(chunk, offset)
    offset += chunk.byteLength
  }
  // 直接传二进制体：Tauri 会把它当作 raw payload，不走 JSON。
  const report = await invoke<{ id: string; files: number; bytes: number }>('pet_write_pack_bundle', payload as never)
  return { id: report.id, dir: '', files: report.files, bytes: report.bytes }
}

export async function readImportAsset(rel: string): Promise<Uint8Array> {
  if (zipSource) {
    const hit = zipSource.get(rel)
    if (!hit) throw new Error(`角色包里没有这个资源：${rel}`)
    return hit
  }
  const buffer = await invoke<ArrayBuffer>('pet_read_import_asset', { rel })
  return new Uint8Array(buffer)
}

export async function installPack(name: string): Promise<InstalledPack> {
  const pack = await invoke<{ id: string; dir: string; files: number; bytes: number }>('pet_install_pack', { name })
  return pack
}

export async function writePackAsset(packId: string, rel: string, bytes: Uint8Array): Promise<void> {
  if (!isRelativeSafePath(rel)) throw new Error(`资源路径不安全：${rel}`)
  await invoke('pet_write_pack_asset', { packId, rel, bytes: Array.from(bytes) })
}

export async function packAsset(packId: string, rel: string): Promise<Uint8Array> {
  const buffer = await invoke<ArrayBuffer>('pet_pack_asset', { packId, rel })
  return new Uint8Array(buffer)
}

export async function pickImportFolder(): Promise<string | null> {
  return await invoke<string | null>('pet_pick_import')
}

export async function pickImportFile(): Promise<string | null> {
  return await invoke<string | null>('pet_pick_import_file')
}

export async function captureMonitorUnderCursor(): Promise<CapturedFrame> {
  const buffer = await invoke<ArrayBuffer>('pet_capture_monitor_under_cursor')
  return decodeCapturedFrame(buffer)
}

export function decodeCapturedFrame(raw: ArrayBuffer | Uint8Array): CapturedFrame {
  const bytes = raw instanceof Uint8Array ? raw : new Uint8Array(raw)
  if (bytes.length < 24) throw new Error('截图数据不完整（可能被系统拦截）')
  const magic = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3])
  if (magic !== 'PETC') throw new Error('截图数据格式不符')
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const width = view.getUint32(4, true)
  const height = view.getUint32(8, true)
  const x = view.getInt32(12, true)
  const y = view.getInt32(16, true)
  const scale = view.getFloat64(20, true)
  const pixels = bytes.subarray(24)
  if (pixels.length < width * height * 4) {
    // 黑屏/受保护内容会得到不完整的缓冲区：明确失败，不冒充正常截图。
    throw new Error('截图内容不完整（受保护窗口或屏幕锁定）')
  }
  return {
    width,
    height,
    x,
    y,
    scale,
    data: new Uint8ClampedArray(pixels.buffer, pixels.byteOffset, width * height * 4),
    capturedAt: Date.now(),
  }
}

/** 角色资源 → blob URL。缓存避免每帧重新取字节。 */
const assetUrls = new Map<string, string>()

export async function packAssetUrl(packId: string, rel: string): Promise<string> {
  const key = `${packId}::${rel}`
  const cached = assetUrls.get(key)
  if (cached) return cached
  const bytes = await packAsset(packId, rel)
  const blob = new Blob([bytes.buffer as ArrayBuffer], { type: mimeFor(rel) })
  const url = URL.createObjectURL(blob)
  assetUrls.set(key, url)
  return url
}

export async function importAssetUrl(rel: string): Promise<string> {
  const key = `import::${importGeneration}::${rel}`
  const cached = assetUrls.get(key)
  if (cached) return cached
  const bytes = await readImportAsset(rel)
  const blob = new Blob([bytes.buffer as ArrayBuffer], { type: mimeFor(rel) })
  const url = URL.createObjectURL(blob)
  assetUrls.set(key, url)
  return url
}

export function resetAssetCache(): void {
  for (const url of assetUrls.values()) URL.revokeObjectURL(url)
  assetUrls.clear()
}

export function mimeFor(rel: string): string {
  const ext = rel.split('.').pop()?.toLowerCase() || ''
  switch (ext) {
    case 'png': return 'image/png'
    case 'jpg':
    case 'jpeg': return 'image/jpeg'
    case 'webp': return 'image/webp'
    case 'gif': return 'image/gif'
    case 'bmp': return 'image/bmp'
    case 'json': return 'application/json'
    default: return 'application/octet-stream'
  }
}

/** 加载图片尺寸，用于自动填碰撞体与精灵框。 */
export function loadImageSize(url: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
    image.onerror = () => reject(new Error('图片无法解码'))
    image.src = url
  })
}

export function frameToCanvas(frame: CapturedFrame): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = frame.width
  canvas.height = frame.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('无法创建画布')
  // 复制一份再交给 ImageData：原始视图可能来自 IPC 的共享缓冲，类型上不接受。
  const pixels = new Uint8ClampedArray(frame.data)
  const image = new ImageData(pixels, frame.width, frame.height)
  context.putImageData(image, 0, 0)
  return canvas
}
