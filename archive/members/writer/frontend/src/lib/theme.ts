export type ThemeStop = {
  color: string
  position: number
}

export const defaultTheme = {
  backdropStart: '#202020',
  backdropEnd: '#202020',
  backdropStops: [
    { color: '#202020', position: 0 },
    { color: '#202020', position: 100 },
  ] as ThemeStop[],
  backdropAngle: 180,
  backdropText: '#f5f5f5',
  mainSurface: '#111111',
  mainSurfaceEnd: '#111111',
  mainStops: [
    { color: '#111111', position: 0 },
    { color: '#111111', position: 100 },
  ] as ThemeStop[],
  mainAngle: 180,
  mainText: '#f5f5f5',
  mainOpacity: 1,
  composerSurface: '#404040',
  composerSurfaceEnd: '#404040',
  composerStops: [
    { color: '#404040', position: 0 },
    { color: '#404040', position: 100 },
  ] as ThemeStop[],
  composerAngle: 180,
  composerText: '#f5f5f5',
  composerOpacity: 1,
  controlSurface: '#404040',
  controlSurfaceEnd: '#404040',
  controlStops: [
    { color: '#404040', position: 0 },
    { color: '#404040', position: 100 },
  ] as ThemeStop[],
  controlAngle: 180,
  controlText: '#f5f5f5',
  controlOpacity: 1,
}

export function normalizeColor(value: unknown, fallback: string) {
  return typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value) ? value : fallback
}

export function clampNumber(value: unknown, min: number, max: number, fallback: number) {
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) return fallback
  return Math.min(max, Math.max(min, numberValue))
}

export function normalizeGradientStops(value: unknown, start: string, end: string): ThemeStop[] {
  const rawStops = Array.isArray(value) ? value : []
  const stops = rawStops
    .map((stop) => {
      if (!stop || typeof stop !== 'object') return null
      const item = stop as Partial<ThemeStop>
      return {
        color: normalizeColor(item.color, start),
        position: clampNumber(item.position, 0, 100, 0),
      }
    })
    .filter((stop): stop is ThemeStop => Boolean(stop))
  const baseStops = stops.length >= 2
    ? stops
    : [
        { color: normalizeColor(start, '#000000'), position: 0 },
        { color: normalizeColor(end, start), position: 100 },
      ]
  return baseStops
    .slice(0, 8)
    .sort((a, b) => a.position - b.position)
    .map((stop, index, source) => ({
      color: stop.color,
      position: index === 0 ? 0 : index === source.length - 1 ? 100 : stop.position,
    }))
}

export function gradientFromStops(angle: number, stops: ThemeStop[], opacity: number) {
  const normalized = normalizeGradientStops(stops, stops[0]?.color || '#000000', stops[stops.length - 1]?.color || '#000000')
  const solidColor = normalized.every((stop) => stop.color.toLowerCase() === normalized[0].color.toLowerCase())
  if (solidColor) return rgbaFromHex(normalized[0].color, opacity)
  const parts = normalized.map((stop) => `${rgbaFromHex(stop.color, opacity)} ${stop.position}%`)
  return `linear-gradient(${clampNumber(angle, 0, 360, 180)}deg, ${parts.join(', ')})`
}

export function rgbaFromHex(hex: string, opacity: number) {
  const clean = normalizeColor(hex, '#000000').slice(1)
  const value = Number.parseInt(clean, 16)
  const red = (value >> 16) & 255
  const green = (value >> 8) & 255
  const blue = value & 255
  return `rgba(${red}, ${green}, ${blue}, ${clampNumber(opacity, 0.1, 1, 1)})`
}

export function hexToRgb(hex: string) {
  const clean = normalizeColor(hex, '#000000').slice(1)
  const value = Number.parseInt(clean, 16)
  return `${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}`
}
