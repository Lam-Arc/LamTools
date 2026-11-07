/**
 * 桌宠指针手势的入口判定（纯函数）。
 *
 * user:“左键、右键、双击必须正确区分”+
 * “右键打开菜单时不能误触发左键 Action”+
 * (只有主键、且按在非 UI 区域时才可能开始抓取/点击；右键交给 contextmenu，
 *  卡片和收纳区自己处理指针。)
 */

export const PET_DRAG_THRESHOLD_PX = 6

export function shouldStartPetGesture(button: number, onUi: boolean): boolean {
  return button === 0 && !onUi
}

export function isPetDrag(movedPx: number): boolean {
  return movedPx > PET_DRAG_THRESHOLD_PX
}

export function isDoubleClick(
  lastPetId: string,
  petId: string,
  elapsedMs: number,
  windowMs = 320,
): boolean {
  return lastPetId === petId && elapsedMs >= 0 && elapsedMs < windowMs
}
