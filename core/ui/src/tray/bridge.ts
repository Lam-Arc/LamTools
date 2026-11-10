/**
 * 托盘面板与宿主的桥接。
 *
 * user:“托盘样式重做”“只做自绘面板”+(面板只调用宿主命令拿状态、切开关、
 * 回主界面和退出；图片、文件、进程都不在页面里碰。)
 */

async function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const module = await import('@tauri-apps/api/core')
  return await module.invoke<T>(command, args)
}

export interface TrayPanelSnapshot {
  pet_open: boolean
  overlay_open: boolean
  panel_open: boolean
}

export type TrayTarget = 'pet' | 'overlay'

export async function panelState(): Promise<TrayPanelSnapshot> {
  return await invoke<TrayPanelSnapshot>('tray_panel_state')
}

/**
 * 切桌宠或标注层。
 *
 * 宿主在后台线程建窗，命令立刻返回；开关状态由页面轮询到真实值。
 */
export async function toggleTarget(target: TrayTarget): Promise<void> {
  await invoke('tray_panel_toggle', { target })
}

/**
 * 窗口材质：mica 表示系统云母已经生效，页面保持透明；
 * solid 表示系统没有云母，页面自己画不透明底色。
 */
export async function panelMaterial(): Promise<'mica' | 'solid'> {
  const value = await invoke<string>('tray_panel_material')
  return value === 'mica' ? 'mica' : 'solid'
}

/**
 * 让宿主把窗口调到刚好装下内容。
 * CSS 尺寸和 dpr 一起报，宿主换算成物理像素，避免缩放不同导致内容被裁。
 */
export async function fitPanel(width: number, height: number, dpr: number): Promise<void> {
  await invoke('tray_panel_fit', { width, height, dpr })
}

export async function closePanel(): Promise<void> {
  await invoke('tray_panel_close')
}

export async function revealMain(): Promise<void> {
  await invoke('tray_panel_reveal_main')
}

export async function quitApp(): Promise<void> {
  await invoke('tray_panel_quit')
}
