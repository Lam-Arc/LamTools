/** Shared colour ladder for the thinking-intensity control. */
export const THINKING_RANKS: Record<string, number> = {
  off: 0,
  light: 1,
  medium: 2,
  high: 3,
  xhigh: 4,
  max: 5,
}

type ColourStop = { at: number; colour: string }

// user:“已有条为绿色，中青蓝，高蓝，极高蓝紫，最高紫”+(每个思考等级一个固定颜色，低到高走冷色阶梯，不做整条渐变)。
const THINKING_STOPS: ColourStop[] = [
  { at: 0, colour: '#9aa0a8' },
  { at: 0.2, colour: '#6fbf95' },
  { at: 0.4, colour: '#55c1c9' },
  { at: 0.6, colour: '#5f9dff' },
  { at: 0.8, colour: '#8b8eff' },
  { at: 1, colour: '#b482f5' },
]

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace('#', '')
  const value = Number.parseInt(clean.length === 3
    ? clean.split('').map((part) => part + part).join('')
    : clean, 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

function rgbToHex(red: number, green: number, blue: number): string {
  return `#${[red, green, blue]
    .map((channel) => Math.round(channel).toString(16).padStart(2, '0'))
    .join('')}`
}

export function mixThinkingColor(from: string, to: string, amount: number): string {
  const t = clamp01(amount)
  if (t === 0) return from
  if (t === 1) return to
  const [r1, g1, b1] = hexToRgb(from)
  const [r2, g2, b2] = hexToRgb(to)
  return rgbToHex(
    r1 + (r2 - r1) * t,
    g1 + (g2 - g1) * t,
    b1 + (b2 - b1) * t,
  )
}

export function sampleThinkingColor(position: number): string {
  const value = clamp01(position)
  for (let index = 1; index < THINKING_STOPS.length; index += 1) {
    const previous = THINKING_STOPS[index - 1]
    const next = THINKING_STOPS[index]
    if (value <= next.at) {
      const span = next.at - previous.at || 1
      return mixThinkingColor(previous.colour, next.colour, (value - previous.at) / span)
    }
  }
  return THINKING_STOPS[THINKING_STOPS.length - 1].colour
}

export function thinkingRank(value: string): number {
  return THINKING_RANKS[value] ?? 0
}

export function thinkingLevelColor(value: string): string {
  return sampleThinkingColor(thinkingRank(value) / 5)
}

export function thinkingGradient(colors: string[]): string {
  if (colors.length === 0) return 'linear-gradient(to top, #8a919c, #8a919c)'
  if (colors.length === 1) return `linear-gradient(to top, ${colors[0]}, ${colors[0]})`
  const stops = colors.map((colour, index) => (
    `${colour} ${(index / (colors.length - 1)) * 100}%`
  ))
  return `linear-gradient(to top, ${stops.join(', ')})`
}
