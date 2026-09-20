type PlotKind = 'function' | 'sequence' | 'limit'

type ExprNode =
  | { type: 'number'; value: number }
  | { type: 'variable'; name: 'x' | 'n' }
  | { type: 'unary'; operator: '+' | '-'; value: ExprNode }
  | { type: 'binary'; operator: '+' | '-' | '*' | '/' | '^'; left: ExprNode; right: ExprNode }
  | { type: 'function'; name: string; value: ExprNode }

interface PlotSeries {
  label: string
  expression: ExprNode
}

interface PlotDefinition {
  kind: PlotKind
  series: PlotSeries[]
  limit?: { variable: string; target: string; value: string; sequence: boolean }
}

interface Token {
  type: 'number' | 'identifier' | 'operator' | 'eof'
  value: string
}

const FUNCTIONS: Record<string, (value: number) => number> = {
  abs: Math.abs,
  acos: Math.acos,
  asin: Math.asin,
  atan: Math.atan,
  ceil: Math.ceil,
  cos: Math.cos,
  exp: Math.exp,
  floor: Math.floor,
  ln: Math.log,
  log: Math.log10,
  sin: Math.sin,
  sqrt: Math.sqrt,
  tan: Math.tan,
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[char] || char)
}

function replaceLatexGroups(source: string): string {
  let value = source
  for (let pass = 0; pass < 12; pass += 1) {
    const previous = value
    value = value
      .replace(/\\(?:dfrac|tfrac|frac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, '(($1)/($2))')
      .replace(/\\(?:dfrac|tfrac|frac)\s*([A-Za-z0-9.]+)\s*\{([^{}]*)\}/g, '(($1)/($2))')
      .replace(/\\(?:dfrac|tfrac|frac)\s*\{([^{}]*)\}\s*([A-Za-z0-9.]+)/g, '(($1)/($2))')
      .replace(/\\sqrt\s*\{([^{}]*)\}/g, 'sqrt($1)')
    if (value === previous) break
  }
  return value
}

function normalizeExpression(source: string): string | null {
  let value = replaceLatexGroups(source.trim())
  value = value
    .replace(/\\(?:quad|qquad).*$/g, '')
    .replace(/,\s*(?:x|n)\s*\\in.*$/g, '')
    .replace(/\\(?:left|right)/g, '')
    .replace(/\\operatorname\s*\{(abs|exp|floor|ceil)\}/g, '$1')
    .replace(/\\mathrm\s*\{e\}/g, 'e')
    .replace(/\\(?:cdot|times)/g, '*')
    .replace(/\\div/g, '/')
    .replace(/\\pi/g, 'pi')
    .replace(/\\(arcsin|arccos|arctan|sin|cos|tan|ln|log|exp|abs|floor|ceil)\s*([A-Za-z])/g, '$1($2)')
    .replace(/\\(?:arcsin|arccos|arctan|sin|cos|tan|ln|log|exp|abs|floor|ceil)\b/g, '$1')
    .replace(/\\lvert/g, '|')
    .replace(/\\rvert/g, '|')
    .replace(/\|([^|]+)\|/g, 'abs($1)')
    .replace(/\\[,;:! ]/g, '')
    .replace(/[{}]/g, match => match === '{' ? '(' : ')')
    .replace(/\s+/g, ' ')
  if (!value || value.length > 240 || value.includes('\\')) return null
  return value
}

function tokenize(source: string): Token[] | null {
  const tokens: Token[] = []
  let index = 0
  while (index < source.length) {
    const rest = source.slice(index)
    const whitespace = rest.match(/^\s+/)
    if (whitespace) {
      index += whitespace[0].length
      continue
    }
    const number = rest.match(/^(?:\d+(?:\.\d*)?|\.\d+)/)
    if (number) {
      tokens.push({ type: 'number', value: number[0] })
      index += number[0].length
      continue
    }
    const identifier = rest.match(/^[A-Za-z]+/)
    if (identifier) {
      tokens.push({ type: 'identifier', value: identifier[0].toLowerCase() })
      index += identifier[0].length
      continue
    }
    const operator = rest[0]
    if ('+-*/^(),'.includes(operator)) {
      tokens.push({ type: 'operator', value: operator })
      index += 1
      continue
    }
    return null
  }
  if (tokens.length > 256) return null
  tokens.push({ type: 'eof', value: '' })
  return tokens
}

class ExpressionParser {
  private index = 0

  constructor(private readonly tokens: Token[]) {}

  parse(): ExprNode | null {
    const result = this.parseExpression()
    return result && this.current().type === 'eof' ? result : null
  }

  private current(): Token { return this.tokens[this.index] }
  private take(): Token { return this.tokens[this.index++] }
  private match(value: string): boolean {
    if (this.current().value !== value) return false
    this.index += 1
    return true
  }

  private parseExpression(): ExprNode | null {
    let left = this.parseTerm()
    if (!left) return null
    while (this.current().value === '+' || this.current().value === '-') {
      const operator = this.take().value as '+' | '-'
      const right = this.parseTerm()
      if (!right) return null
      left = { type: 'binary', operator, left, right }
    }
    return left
  }

  private parseTerm(): ExprNode | null {
    let left = this.parseUnary()
    if (!left) return null
    while (true) {
      const explicit = this.current().value === '*' || this.current().value === '/'
      const implicit = this.current().type === 'number' || this.current().type === 'identifier' || this.current().value === '('
      if (!explicit && !implicit) break
      const operator = explicit ? this.take().value as '*' | '/' : '*'
      const right = this.parseUnary()
      if (!right) return null
      left = { type: 'binary', operator, left, right }
    }
    return left
  }

  private parseUnary(): ExprNode | null {
    if (this.current().value === '+' || this.current().value === '-') {
      const operator = this.take().value as '+' | '-'
      const value = this.parseUnary()
      return value ? { type: 'unary', operator, value } : null
    }
    return this.parsePower()
  }

  private parsePower(): ExprNode | null {
    const left = this.parsePrimary()
    if (!left) return null
    if (!this.match('^')) return left
    const right = this.parseUnary()
    return right ? { type: 'binary', operator: '^', left, right } : null
  }

  private parsePrimary(): ExprNode | null {
    const token = this.current()
    if (token.type === 'number') {
      this.take()
      const value = Number(token.value)
      return Number.isFinite(value) ? { type: 'number', value } : null
    }
    if (token.type === 'identifier') {
      this.take()
      if (token.value === 'x' || token.value === 'n') return { type: 'variable', name: token.value }
      if (token.value === 'pi') return { type: 'number', value: Math.PI }
      if (token.value === 'e') return { type: 'number', value: Math.E }
      if (!(token.value in FUNCTIONS)) return null
      let value: ExprNode | null
      if (this.match('(')) {
        value = this.parseExpression()
        if (!value || !this.match(')')) return null
      } else value = this.parseUnary()
      return value ? { type: 'function', name: token.value, value } : null
    }
    if (this.match('(')) {
      const value = this.parseExpression()
      return value && this.match(')') ? value : null
    }
    return null
  }
}

function parseExpression(source: string): ExprNode | null {
  const normalized = normalizeExpression(source)
  const tokens = normalized ? tokenize(normalized) : null
  return tokens ? new ExpressionParser(tokens).parse() : null
}

function variables(node: ExprNode, result = new Set<'x' | 'n'>()): Set<'x' | 'n'> {
  if (node.type === 'variable') result.add(node.name)
  else if (node.type === 'unary' || node.type === 'function') variables(node.value, result)
  else if (node.type === 'binary') { variables(node.left, result); variables(node.right, result) }
  return result
}

function evaluate(node: ExprNode, input: number, variable: 'x' | 'n'): number {
  if (node.type === 'number') return node.value
  if (node.type === 'variable') return node.name === variable ? input : Number.NaN
  if (node.type === 'unary') {
    const value = evaluate(node.value, input, variable)
    return node.operator === '-' ? -value : value
  }
  if (node.type === 'function') return FUNCTIONS[node.name](evaluate(node.value, input, variable))
  const left = evaluate(node.left, input, variable)
  const right = evaluate(node.right, input, variable)
  if (node.operator === '+') return left + right
  if (node.operator === '-') return left - right
  if (node.operator === '*') return left * right
  if (node.operator === '/') return right === 0 ? Number.NaN : left / right
  return left ** right
}

function plainMathLabel(source: string): string {
  const subscripts: Record<string, string> = { '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉' }
  return source.trim()
    .replace(/\\infty/g, '∞')
    .replace(/\\pi/g, 'π')
    .replace(/_\{?([0-9]+)\}?/g, (_match, digits: string) => [...digits].map(digit => subscripts[digit] || digit).join(''))
    .replace(/[{}]/g, '')
    .replace(/\\([A-Za-z]+)/g, '$1')
    .replace(/\s+/g, '')
    .slice(0, 32)
}

function extractDefinition(latex: string, allowStandalone: boolean): PlotDefinition | null {
  const cleaned = latex
    .replace(/\\(?:left|right)/g, '')
    .replace(/\\displaystyle/g, '')
    .replace(/\\begin\{(?:aligned\*?|align\*?|gathered|gather)\}/g, '')
    .replace(/\\end\{(?:aligned\*?|align\*?|gathered|gather)\}/g, '')
    .replace(/\\(?:tag|label)\s*\{[^{}]*\}/g, '')
    .replace(/&/g, '')
  const limitSource = cleaned.replace(/(\\lim(?:\\limits)?\s*_\s*\{[^{}]*[A-Za-z])_\{([^{}]+)\}([^{}]*\})/, '$1_$2$3')
  const limit = limitSource.match(/\\lim(?:\\limits)?\s*_\s*\{\s*([A-Za-z])\s*\\to\s*([^}]+)\}\s*(.+?)\s*=\s*([^=]+)$/)
  if (limit) {
    return {
      kind: 'limit',
      series: [],
      limit: {
        variable: plainMathLabel(limit[1]),
        target: plainMathLabel(limit[2]),
        value: plainMathLabel(limit[4].replace(/[,.，。;；]+$/, '')),
        sequence: limit[1].toLowerCase() === 'n' && (/\\infty/.test(limit[2]) || /_\{?n\}?/.test(limit[3])),
      },
    }
  }
  const lines = cleaned.split(/\\\\|\r?\n/).map(line => line.trim()).filter(Boolean)
  const functions: PlotSeries[] = []
  const sequences: PlotSeries[] = []

  for (const line of lines) {
    const sequence = line.match(/^([A-Za-z])\s*_\s*(?:\{\s*n\s*\}|n)\s*=\s*(.+)$/)
    const fn = line.match(/^(y|[A-Za-z]\s*\(\s*x\s*\))\s*=\s*(.+)$/)
    const kind: PlotKind | null = sequence ? 'sequence' : fn ? 'function' : null
    const rhs = sequence?.[2] || fn?.[2]
    const label = sequence?.[1] ? `${sequence[1]}ₙ` : fn?.[1]?.replace(/\s+/g, '')
    if (!kind || !rhs || !label) continue
    const expression = parseExpression(rhs)
    if (!expression) continue
    const used = variables(expression)
    if (kind === 'function' && used.has('n')) continue
    if (kind === 'sequence' && used.has('x')) continue
    ;(kind === 'function' ? functions : sequences).push({ label, expression })
  }

  if (allowStandalone && !functions.length && !sequences.length && lines.length === 1 && !lines[0].includes('=')) {
    const expression = parseExpression(lines[0])
    if (expression && variables(expression).has('x')) functions.push({ label: 'y', expression })
  }
  if (functions.length) return { kind: 'function', series: functions.slice(0, 3) }
  if (sequences.length) return { kind: 'sequence', series: sequences.slice(0, 3) }
  return null
}

function quantile(sorted: number[], ratio: number): number {
  const position = (sorted.length - 1) * ratio
  const low = Math.floor(position)
  const high = Math.ceil(position)
  const fraction = position - low
  return sorted[low] * (1 - fraction) + sorted[high] * fraction
}

function formatTick(value: number): string {
  if (Math.abs(value) < 1e-9) return '0'
  if (Math.abs(value) >= 1000 || Math.abs(value) < .01) return value.toExponential(1)
  return Number(value.toFixed(2)).toString()
}

function renderLimitPlot(definition: PlotDefinition): string {
  const width = 640
  const height = 320
  const centerX = 330
  const centerY = 148
  const variable = definition.limit?.variable || 'x'
  const target = definition.limit?.target || 'x₀'
  const value = definition.limit?.value || 'A'
  const description = definition.limit?.sequence
    ? `数列极限示意：${variable} → ${target} 时，数列项趋近 ${value}；点列仅为趋近关系示意`
    : `极限示意：${variable} → ${target} 时，函数值趋近 ${value}；曲线仅为趋近关系示意`
  if (definition.limit?.sequence) {
    const points = Array.from({ length: 12 }, (_, index) => {
      const x = 94 + index * 43
      const y = centerY + 92 * (.72 ** index)
      return `<circle cx="${x}" cy="${y}" r="3.4"/>`
    }).join('')
    return `<figure class="math-auto-plot" data-math-auto-plot="limit"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(description)}"><line class="math-auto-plot-grid" x1="48" y1="${centerY}" x2="622" y2="${centerY}"/><line class="math-auto-plot-axis" x1="48" y1="264" x2="622" y2="264"/><line class="math-auto-plot-axis" x1="66" y1="18" x2="66" y2="282"/><line class="math-auto-plot-limit-guide" x1="66" y1="${centerY}" x2="622" y2="${centerY}"/><g class="math-auto-plot-series math-auto-plot-series--0 math-auto-plot-limit-sequence">${points}</g><text class="math-auto-plot-label math-auto-plot-limit-label" x="56" y="${centerY + 4}" text-anchor="end">${escapeHtml(value)}</text><text class="math-auto-plot-label" x="615" y="281" text-anchor="end">${escapeHtml(variable)}</text></svg><figcaption>${escapeHtml(description)}</figcaption></figure>`
  }
  return `<figure class="math-auto-plot" data-math-auto-plot="limit"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(description)}"><line class="math-auto-plot-grid" x1="48" y1="${centerY}" x2="622" y2="${centerY}"/><line class="math-auto-plot-grid" x1="${centerX}" y1="18" x2="${centerX}" y2="282"/><line class="math-auto-plot-axis" x1="48" y1="264" x2="622" y2="264"/><line class="math-auto-plot-axis" x1="66" y1="18" x2="66" y2="282"/><line class="math-auto-plot-limit-guide" x1="${centerX}" y1="${centerY}" x2="${centerX}" y2="264"/><line class="math-auto-plot-limit-guide" x1="66" y1="${centerY}" x2="${centerX}" y2="${centerY}"/><path class="math-auto-plot-series math-auto-plot-series--0" d="M70,238 C145,230 226,184 322,151"/><path class="math-auto-plot-series math-auto-plot-series--0" d="M338,145 C430,114 520,82 612,90"/><circle class="math-auto-plot-limit-point" cx="${centerX}" cy="${centerY}" r="5"/><text class="math-auto-plot-label math-auto-plot-limit-label" x="${centerX}" y="281" text-anchor="middle">${escapeHtml(target)}</text><text class="math-auto-plot-label math-auto-plot-limit-label" x="56" y="${centerY + 4}" text-anchor="end">${escapeHtml(value)}</text><text class="math-auto-plot-label" x="615" y="281" text-anchor="end">${escapeHtml(variable)}</text></svg><figcaption>${escapeHtml(description)}</figcaption></figure>`
}

function renderPlot(definition: PlotDefinition): string | null {
  if (definition.kind === 'limit') return renderLimitPlot(definition)
  const width = 640
  const height = 320
  const left = 48
  const right = 18
  const top = 18
  const bottom = 38
  const plotWidth = width - left - right
  const plotHeight = height - top - bottom
  const xMin = definition.kind === 'function' ? -5 : 1
  const xMax = definition.kind === 'function' ? 5 : 12
  const sampleCount = definition.kind === 'function' ? 241 : 12
  const sampled = definition.series.map(series => Array.from({ length: sampleCount }, (_, index) => {
    const x = definition.kind === 'function' ? xMin + (xMax - xMin) * index / (sampleCount - 1) : index + 1
    return { x, y: evaluate(series.expression, x, definition.kind === 'function' ? 'x' : 'n') }
  }))
  const finite = sampled.flat().map(point => point.y).filter(value => Number.isFinite(value) && Math.abs(value) <= 1e6).sort((a, b) => a - b)
  if (finite.length < 2) return null

  let yMin = definition.kind === 'function' && finite.length > 40 ? quantile(finite, .02) : finite[0]
  let yMax = definition.kind === 'function' && finite.length > 40 ? quantile(finite, .98) : finite[finite.length - 1]
  if (yMin === yMax) { const amount = Math.max(1, Math.abs(yMin) * .2); yMin -= amount; yMax += amount }
  const initialSpan = yMax - yMin
  if (yMin > 0 && yMin <= initialSpan * 2) yMin = 0
  if (yMax < 0 && Math.abs(yMax) <= initialSpan * 2) yMax = 0
  const padding = Math.max((yMax - yMin) * .08, .1)
  yMin -= padding
  yMax += padding
  const ySpan = yMax - yMin
  const px = (x: number) => left + (x - xMin) / (xMax - xMin) * plotWidth
  const py = (y: number) => top + (yMax - y) / ySpan * plotHeight

  const grid: string[] = []
  for (let index = 0; index <= 5; index += 1) {
    const x = xMin + (xMax - xMin) * index / 5
    const screenX = px(x)
    grid.push(`<line class="math-auto-plot-grid" x1="${screenX}" y1="${top}" x2="${screenX}" y2="${top + plotHeight}"/>`)
    grid.push(`<text class="math-auto-plot-label" x="${screenX}" y="${height - 14}" text-anchor="middle">${formatTick(x)}</text>`)
  }
  for (let index = 0; index <= 4; index += 1) {
    const y = yMin + (yMax - yMin) * index / 4
    const screenY = py(y)
    grid.push(`<line class="math-auto-plot-grid" x1="${left}" y1="${screenY}" x2="${left + plotWidth}" y2="${screenY}"/>`)
    grid.push(`<text class="math-auto-plot-label" x="${left - 7}" y="${screenY + 4}" text-anchor="end">${formatTick(y)}</text>`)
  }
  if (xMin <= 0 && xMax >= 0) grid.push(`<line class="math-auto-plot-axis" x1="${px(0)}" y1="${top}" x2="${px(0)}" y2="${top + plotHeight}"/>`)
  if (yMin <= 0 && yMax >= 0) grid.push(`<line class="math-auto-plot-axis" x1="${left}" y1="${py(0)}" x2="${left + plotWidth}" y2="${py(0)}"/>`)

  const plots = sampled.map((points, seriesIndex) => {
    if (definition.kind === 'sequence') {
      const line = points.filter(point => Number.isFinite(point.y)).map(point => `${px(point.x)},${py(point.y)}`).join(' ')
      const circles = points.filter(point => Number.isFinite(point.y) && point.y >= yMin && point.y <= yMax)
        .map(point => `<circle cx="${px(point.x)}" cy="${py(point.y)}" r="3.2"/>`).join('')
      return `<g class="math-auto-plot-series math-auto-plot-series--${seriesIndex}"><polyline points="${line}"/>${circles}</g>`
    }
    let path = ''
    let drawing = false
    let previousY = 0
    for (const point of points) {
      const visible = Number.isFinite(point.y) && point.y >= yMin - ySpan && point.y <= yMax + ySpan
      const screenY = visible ? py(point.y) : 0
      if (!visible || drawing && Math.abs(screenY - previousY) > plotHeight * .72) {
        drawing = false
        continue
      }
      path += `${drawing ? 'L' : 'M'}${px(point.x).toFixed(2)},${screenY.toFixed(2)}`
      drawing = true
      previousY = screenY
    }
    return `<path class="math-auto-plot-series math-auto-plot-series--${seriesIndex}" d="${path}"/>`
  }).join('')

  const labels = definition.series.map(series => series.label).join('、')
  const description = definition.kind === 'function' ? `函数图像：${labels}，横轴范围 -5 到 5` : `数列图像：${labels}，显示前 12 项`
  return `<figure class="math-auto-plot" data-math-auto-plot="${definition.kind}"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(description)}">${grid.join('')}${plots}</svg><figcaption>${escapeHtml(description)}</figcaption></figure>`
}

export function renderAutoMathPlot(latex: string, options: { allowStandalone?: boolean } = {}): string {
  const definition = extractDefinition(latex, options.allowStandalone !== false)
  return definition ? renderPlot(definition) || '' : ''
}
