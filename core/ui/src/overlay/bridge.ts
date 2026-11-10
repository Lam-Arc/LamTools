/**
 * 交互层与宿主的桥接。
 *
 * user:“AI 直接在屏幕上标记、绘制、互动”+(覆盖层只调用宿主命令和 Core HTTP：
 * 建窗、报命中矩形、心跳、取窗口几何；不直接碰文件或系统 API)。
 */
import {
  apiBase,
  desktopWindows,
  type OverlayBounds,
  type PetDesktopWindow,
} from '@/pet/bridge.ts'

export type { OverlayBounds, PetDesktopWindow }

async function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const module = await import('@tauri-apps/api/core')
  return await module.invoke<T>(command, args)
}

export { apiBase }

/** 覆盖层窗口的虚拟桌面边界，物理像素。 */
export async function openOverlay(): Promise<OverlayBounds> {
  return await invoke<OverlayBounds>('desktop_overlay_open')
}

/** 页面启动时读到的虚拟桌面边界，不动窗口。 */
export async function overlayBounds(): Promise<OverlayBounds> {
  return await invoke<OverlayBounds>('desktop_overlay_bounds')
}

export async function overlayReady(): Promise<void> {
  await invoke('desktop_overlay_ready')
}

export async function closeOverlay(): Promise<void> {
  await invoke('desktop_overlay_close')
}

export async function heartbeat(): Promise<void> {
  await invoke('desktop_overlay_heartbeat')
}

/** 页面上可点区域，物理像素屏幕坐标 [x, y, w, h]。 */
export async function setInteractiveRects(rects: number[][]): Promise<void> {
  await invoke('desktop_overlay_set_rects', { rects })
}

/** 当前真实桌面窗口，用于标记跟随。 */
export async function screenWindows(): Promise<PetDesktopWindow[]> {
  return await desktopWindows()
}

export interface OverlaySettings {
  danmaku_speed: number
  danmaku_font: string
  danmaku_size: number
}

/** 弹幕倍速、字体、字号：存在桌宠配置里，由宿主读给页面。 */
export async function fetchSettings(): Promise<OverlaySettings> {
  return await invoke<OverlaySettings>('desktop_overlay_settings')
}

/** 设置改完通知页面重读，不用重启窗口。 */
export async function onSettingsChanged(handler: () => void): Promise<() => void> {
  const module = await import('@tauri-apps/api/event')
  return await module.listen('overlay://settings', () => handler())
}

export interface OverlayStateResponse {
  version: number
  server_time: number
  marks: import('./model.ts').OverlayMark[]
  /** 外部 API 请求的一次圈选，页面取走之后变回 false。 */
  capture_requested?: boolean
}

export async function fetchState(base: string): Promise<OverlayStateResponse> {
  const response = await fetch(`${base}/api/core/overlay/state`)
  if (!response.ok) throw new Error(`标注状态读取失败（${response.status}）`)
  return (await response.json()) as OverlayStateResponse
}

/**
 * 取一次挂起的圈选请求：热键先按下、页面后加载时靠它补上。
 * user:“没必要搞那个圈选批注的键，就是把它的入口设成跟 ping 一样就行”+
 * (入口改成全局热键，工具条上不再常驻一个框)。
 */
export async function takeCaptureRequest(): Promise<boolean> {
  return await invoke<boolean>('desktop_overlay_take_capture')
}

/** 监听圈选热键：层已经开着时直接进框选态。 */
export async function onCaptureRequest(handler: () => void): Promise<() => void> {
  const module = await import('@tauri-apps/api/event')
  return await module.listen('overlay://capture', () => handler())
}

/** 圈选交给 Ping 的截图编辑器：交互层自己不再收输入。 */
export async function openCaptureRegion(region: [number, number, number, number]): Promise<void> {
  // user:“合并，这样更干净”+(圈选直接进 Ping 的截图编辑器，带选区过去)。
  await invoke('pet_ping_capture_open', { region })
}

/** 告诉 Core 这次圈选请求已经用掉了，别重复触发。 */
export async function clearCaptureRequest(base: string): Promise<void> {
  const response = await fetch(`${base}/api/core/overlay/control`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'capture_ack' }),
  })
  if (!response.ok) throw new Error(`确认圈选请求失败（${response.status}）`)
}

export async function clearMarks(base: string, all: boolean, ids: string[] = []): Promise<void> {
  const response = await fetch(`${base}/api/core/overlay/control`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'clear', all, ids }),
  })
  if (!response.ok) throw new Error(`清除标注失败（${response.status}）`)
}
