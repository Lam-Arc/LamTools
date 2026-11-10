/**
 * 桌面窗口几何指纹。
 *
 * user:“第 1 点就是我怀疑桌宠的建图并不是实时去建的，而是只在桌宠启动后去建”+
 * (窗口枚举现在常驻刷新，但瓦片图重建很贵：必须先在本地判断这份窗口几何
 *  和上次是不是同一份，只有真的变了才把地形换掉、才让瓦片图重建，
 *  否则每轮枚举都会白打一次图。)
 */
import type { DesktopWindow } from './terrain.ts'

/**
 * 指纹包含顺序与 z：L2 平台的可见性裁剪按 z 序计算，
 * 仅仅发生层级反转也会改变某条平台线露出多少，所以顺序变化同样算变化。
 */
export function windowFingerprint(windows: readonly DesktopWindow[]): string {
  return windows
    .map((window, index) => {
      const { x, y, width, height } = window.bounds
      const rect = `${Math.round(x)},${Math.round(y)},${Math.round(width)},${Math.round(height)}`
      return `${index}:${window.id}:${rect}:${window.z}`
    })
    .join('|')
}
