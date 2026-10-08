// Tiny animation kit for scene pages.
//
// Scenes are rendered frame by frame, so every visual property must be a pure
// function of time: no CSS transitions, no rAF loops, no wall clock.  These
// helpers keep that style short to write.  It is a classic script on purpose —
// ES module imports are blocked for file:// pages.

window.MotionKit = (() => {
  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value))
  const lerp = (a, b, p) => a + (b - a) * p

  // Normalised progress of `t` inside [from, to]; 0 before, 1 after.
  const seg = (t, from, to) => (to <= from ? (t >= to ? 1 : 0) : clamp((t - from) / (to - from)))

  const ease = {
    linear: (p) => p,
    cubicOut: (p) => 1 - Math.pow(1 - p, 3),
    quartOut: (p) => 1 - Math.pow(1 - p, 4),
    quintOut: (p) => 1 - Math.pow(1 - p, 5),
    // Long, calm settle — the house easing for this film's camera moves.
    expoOut: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
    sineInOut: (p) => -(Math.cos(Math.PI * p) - 1) / 2,
    cubicInOut: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    // Damped spring: overshoots, then settles — for things that land with weight.
    spring: (p) => (p >= 1 ? 1 : 1 - Math.exp(-5 * p) * Math.cos(9 * p)),
    // Barely-there overshoot, for elements that "land".
    softBack: (p) => {
      const c = 1.12
      const q = p - 1
      return 1 + (c + 1) * q * q * q + c * q * q
    },
  }

  /** Interpolate a hex colour string (#rrggbb). */
  const mixColor = (from, to, p) => {
    const parse = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
    const [r1, g1, b1] = parse(from)
    const [r2, g2, b2] = parse(to)
    const channel = (a, b) => Math.round(lerp(a, b, p))
    return `rgb(${channel(r1, r2)}, ${channel(g1, g2)}, ${channel(b1, b2)})`
  }

  /** Animate a number through a segment with easing; returns a plain number. */
  const at = (t, from, to, startValue, endValue, easing = ease.expoOut) =>
    lerp(startValue, endValue, easing(seg(t, from, to)))

  // CSS properties that must NOT get a "px" suffix.  Getting this wrong fails
  // silently: `opacity: 0.9px` is invalid, the browser drops it, and the
  // element simply never appears.
  const UNITLESS = new Set([
    'opacity',
    'zIndex',
    'flex',
    'flexGrow',
    'flexShrink',
    'order',
    'lineHeight',
    'fontWeight',
    'zoom',
    'fillOpacity',
    'strokeOpacity',
    'strokeWidth',
    'strokeDasharray',
    'strokeDashoffset',
  ])

  /** Apply several style properties at once. */
  const style = (node, properties) => {
    for (const [key, value] of Object.entries(properties)) {
      if (value === null || value === undefined) continue
      if (typeof value !== 'number' || UNITLESS.has(key)) {
        node.style[key] = String(value)
      } else {
        node.style[key] = `${value}px`
      }
    }
  }

  /** Cascading reveal: item `index` of `total` starts a little after the last. */
  const stagger = (t, index, { start = 0, each = 0.035, dur = 0.5 } = {}) =>
    seg(t, start + index * each, start + index * each + dur)

  /** Camera keyframes -> transform string for a world container. */
  const cameraTransform = (from, to, p, easing = ease.sineInOut) => {
    const k = lerp(from.k, to.k, easing(p))
    const x = lerp(from.x, to.x, easing(p))
    const y = lerp(from.y, to.y, easing(p))
    return `translate(${(-800 + x).toFixed(2)}px, ${(-450 + y).toFixed(2)}px) scale(${k.toFixed(5)})`
  }

  const blur = (node, px) => {
    node.style.filter = px > 0.05 ? `blur(${px.toFixed(2)}px)` : 'none'
  }

  return { clamp, lerp, seg, at, ease, mixColor, style, stagger, cameraTransform, blur }
})()
