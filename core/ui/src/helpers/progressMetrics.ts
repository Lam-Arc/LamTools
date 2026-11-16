// user:“确保视觉、功能和交互不退化”+(无效、负数或超限进度保持可读且无障碍数值在合法范围内)。
export function progressMetrics(value: unknown, max: unknown = 100) {
  const parsedValue = Number(value)
  const parsedMax = Number(max)
  const raw = Number.isFinite(parsedValue) ? parsedValue : 0
  const maximum = Number.isFinite(parsedMax) && parsedMax > 0 ? parsedMax : 100
  const current = Math.min(maximum, Math.max(0, raw))
  return { raw, maximum, current, ratio: current / maximum }
}
