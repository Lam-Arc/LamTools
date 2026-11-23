/**
 * user:“按对角线”+(玻璃边的明暗分界要沿元素对角线，而不是固定 45°；
 * 右上角相对于正上方的角度 = atan2(width, height)，同时由它决定左右两条分界：
 * 右上角 θ、左下角 180°+θ)。
 *
 * 尺寸无效（首帧未布局、display:none）时退回 45°，保证首帧也有边。
 */
export function messageSurfaceEdgeAngle(width: number, height: number): number {
  if (!(width > 0) || !(height > 0)) return 45
  return (Math.atan2(width, height) * 180) / Math.PI
}
