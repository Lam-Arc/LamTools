/**
 * 样式资产 —— 把项目里的样式表读成资料库里的「可渲染资产」。
 *
 * user:“将本项目的所有样式做完为第一批 library 增强试验”+(资料库不能只放文件；
 * 样式表本身就是可复用的素材，要能直接看到它长什么样，而不是只看到一段代码)。
 *
 * 这一层只做读取与解析，不碰界面：
 * - 用 Vite 的 `?raw` 把样式表原文读进来，桌面端与浏览器预览用的是同一份数据；
 * - 从原文里拆出变量（设计令牌）、颜色、选择器与规则体；
 * - 把「只有类名的后代选择器」还原成嵌套标签，交给界面原样渲染——
 *   这样每一张卡片显示的都是这套样式真实作用于界面的样子。
 */

/** 样式表在资料库里的分类。分组只服务于浏览，不改变任何样式本身。 */
export type StyleAssetCategory =
  | 'tokens'
  | 'shell'
  | 'library'
  | 'chat'
  | 'settings'
  | 'plugins'
  | 'studio'
  | 'controls'
  | 'pet'
  | 'study';

export interface StyleTokenEntry {
  /** 变量名，含 `--` 前缀。 */
  name: string
  value: string
  kind: 'color' | 'size' | 'motion' | 'font' | 'shadow' | 'other'
}

export interface StyleSpecimen {
  /** 原始选择器，用来在详情里说明这段样本对应哪条规则。 */
  selector: string
  /** 由选择器还原出的嵌套标签。 */
  html: string
}

export interface StyleAsset {
  id: string
  /** 人话名字，例如「资料库表面」。 */
  name: string
  /** 工作区相对路径，例如 `styles/library-surface.css`。 */
  file: string
  category: StyleAssetCategory
  /** 文件头注释里的一句话，没有就留空。 */
  purpose: string
  lines: number
  ruleCount: number
  tokenCount: number
  classCount: number
  tokens: StyleTokenEntry[]
  /** 出现次数最多的颜色字面量，用作资产的颜色条。 */
  palette: string[]
  specimen: StyleSpecimen[]
  /** 卡片上直接渲染的那几段样本。 */
  preview: string
  raw: string
}

const STYLE_MODULES = import.meta.glob('../styles/*.css', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** 资料库收的是项目里所有手写样式，桌宠与学习模式的样式表不在 styles/ 下。 */
const EXTRA_MODULES = import.meta.glob(['../pet/ui/*.css', '../study/*.css'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const CATEGORY_LABEL: Record<StyleAssetCategory, string> = {
  tokens: '令牌',
  shell: '外壳',
  library: '资料库',
  chat: '会话',
  settings: '设置',
  plugins: '插件',
  studio: '主题工作室',
  controls: '控件',
  pet: '桌宠',
  study: '学习',
}

/** 文件名 → 人话名字与分类。没列到的文件按「其他样式」处理，不会丢。 */
const CATALOG: Record<string, { name: string; category: StyleAssetCategory }> = {
  'variables.css': { name: '设计令牌', category: 'tokens' },
  'base.css': { name: '基础排版', category: 'tokens' },
  'layout.css': { name: '主布局', category: 'shell' },
  'workspace-shell.css': { name: '工作台外壳', category: 'shell' },
  'app-page.css': { name: '全版容器', category: 'shell' },
  'session-sidebar.css': { name: '会话栏', category: 'shell' },
  'split-workspace.css': { name: '分屏工作台', category: 'shell' },
  'optical-glass.css': { name: '光学玻璃', category: 'shell' },
  'library-surface.css': { name: '资料库表面', category: 'library' },
  'library-styles.css': { name: '样式资产版面', category: 'library' },
  'theme-editor.css': { name: '主题工作室', category: 'studio' },
  'sunday-controls.css': { name: '交互控件', category: 'controls' },
  'chat-thread-shell.css': { name: '消息流外壳', category: 'chat' },
  'chat-thread-cards.css': { name: '工具与卡片', category: 'chat' },
  'chat-thread-process.css': { name: '执行过程', category: 'chat' },
  'chat-thread-reasoning.css': { name: '思考过程', category: 'chat' },
  'chat-thread-tools.css': { name: '工具调用', category: 'chat' },
  'chat-thread-editing.css': { name: '消息编辑', category: 'chat' },
  'auxiliary-chat.css': { name: '辅助会话', category: 'chat' },
  'core-settings-surface.css': { name: '设置表面', category: 'settings' },
  'core-settings-base.css': { name: '设置基础', category: 'settings' },
  'core-settings-workspace.css': { name: '工作区设置', category: 'settings' },
  'core-settings-models.css': { name: '模型设置', category: 'settings' },
  'core-settings-model-editor.css': { name: '模型编辑', category: 'settings' },
  'core-settings-permissions.css': { name: '权限设置', category: 'settings' },
  'core-model-catalog.css': { name: '模型目录', category: 'settings' },
  'plugin-editor-shell.css': { name: '插件编辑外壳', category: 'plugins' },
  'plugin-editor-cards.css': { name: '插件卡片', category: 'plugins' },
  'plugin-editor-details.css': { name: '插件详情', category: 'plugins' },
  'plugin-editor-states.css': { name: '插件状态', category: 'plugins' },
  'pet-surface.css': { name: '桌宠表面', category: 'pet' },
  'study.css': { name: '学习模式', category: 'study' },
}

const CATEGORY_ORDER: StyleAssetCategory[] = [
  'tokens', 'shell', 'library', 'chat', 'settings', 'plugins', 'studio', 'controls', 'pet', 'study',
]

/** 样本里的文字按类名给：同一个词重复三十遍只会变成噪音。 */
function sampleText(classes: string[]): string {
  const joined = classes.join(' ')
  if (/title|heading/.test(joined)) return '标题'
  if (/name/.test(joined)) return '名称'
  if (/desc|hint|sub|note|caption|summary/.test(joined)) return '说明文字'
  if (/meta|count|time|date|size|num/.test(joined)) return '12'
  if (/tag|label|chip|pill|badge|status/.test(joined)) return '标签'
  if (/search|field|input/.test(joined)) return '搜索'
  if (/placeholder/.test(joined)) return '输入内容'
  // 兜底也要有变化：整面墙三十张卡片都写「内容」，读起来就是噪音。
  const pool = ['内容', '说明', '条目', '示例', '预览']
  let hash = 0
  for (const char of joined) hash = (hash * 31 + char.charCodeAt(0)) % 997
  return pool[hash % pool.length]
}

/* ── 原文扫描 ──────────────────────────────────────────────────────────── */

/** 注释换成同长度空格，行号与括号位置都不动，后面的扫描可以只认结构。 */
export function stripComments(css: string): string {
  let out = ''
  let index = 0
  while (index < css.length) {
    const char = css[index]
    if (char === '/' && css[index + 1] === '*') {
      const end = css.indexOf('*/', index + 2)
      const stop = end === -1 ? css.length : end + 2
      out += css.slice(index, stop).replace(/[^\n]/g, ' ')
      index = stop
      continue
    }
    out += char
    index += 1
  }
  return out
}

export interface CssRule {
  selector: string
  body: string
}

function skipString(text: string, start: number): number {
  const quote = text[start]
  let index = start + 1
  while (index < text.length) {
    if (text[index] === '\\') { index += 2; continue }
    if (text[index] === quote) return index + 1
    index += 1
  }
  return index
}

function matchingBrace(text: string, open: number): number {
  let depth = 0
  let index = open
  while (index < text.length) {
    const char = text[index]
    if (char === '"' || char === "'") { index = skipString(text, index); continue }
    if (char === '{') depth += 1
    else if (char === '}') {
      depth -= 1
      if (depth === 0) return index
    }
    index += 1
  }
  return text.length
}

/**
 * 拆出「选择器 + 规则体」。只收顶层与一层 @media/@supports/@container 里的规则，
 * 再往里的嵌套媒体查询不参与样本生成，免得一条规则被重复渲染。
 */
export function collectRules(css: string): CssRule[] {
  const text = stripComments(css)
  const rules: CssRule[] = []
  let index = 0
  let depth = 0
  let preludeStart = 0
  while (index < text.length) {
    const char = text[index]
    if (char === '"' || char === "'") { index = skipString(text, index); continue }
    if (char === '{') {
      const prelude = text.slice(preludeStart, index).trim()
      if (prelude.startsWith('@')) {
        depth += 1
        preludeStart = index + 1
        index += 1
        continue
      }
      const close = matchingBrace(text, index)
      if (depth <= 1 && prelude) rules.push({ selector: prelude, body: text.slice(index + 1, close) })
      index = close + 1
      preludeStart = index
      continue
    }
    if (char === '}') {
      depth = Math.max(0, depth - 1)
      preludeStart = index + 1
      index += 1
      continue
    }
    index += 1
  }
  return rules
}

/* ── 变量与颜色 ────────────────────────────────────────────────────────── */

const NAMED_COLORS = new Set([
  'transparent', 'currentcolor', 'inherit', 'white', 'black', 'red', 'blue', 'green',
  'orange', 'purple', 'yellow', 'gray', 'grey', 'pink', 'teal', 'navy',
])

function tokenKind(value: string): StyleTokenEntry['kind'] {
  const text = value.trim().toLowerCase()
  if (/^(#|rgb|hsl|oklch|lab|lch|color\()/.test(text)) return 'color'
  if (NAMED_COLORS.has(text)) return 'color'
  if (text.startsWith('color-mix(')) return 'color'
  if (/var\(--(theme|bg|panel|text|line|green|blue|orange|purple|red|yellow|muted|faint)/.test(text)) return 'color'
  if (/^-?[\d.]+(px|rem|em|%|vw|vh|ch|pt|deg)$/.test(text)) return 'size'
  if (/^-?[\d.]+(ms|s)$/.test(text) || text.startsWith('cubic-bezier')) return 'motion'
  if (text.includes('rgba(') || (text.includes('px') && /\d+px\s+\d+px/.test(text))) return 'shadow'
  if (text.includes('"') || text.includes('sans-serif') || text.includes('monospace') || text.startsWith('var(--font')) return 'font'
  return 'other'
}

export function collectTokens(css: string): StyleTokenEntry[] {
  const text = stripComments(css)
  const seen = new Map<string, StyleTokenEntry>()
  const pattern = /(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+)/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text))) {
    const name = match[1]
    const value = match[2].trim().replace(/\s+/g, ' ')
    if (!value || seen.has(name)) continue
    seen.set(name, { name, value, kind: tokenKind(value) })
  }
  return [...seen.values()]
}

export function collectPalette(css: string): string[] {
  const text = stripComments(css).toLowerCase()
  const counts = new Map<string, number>()
  const pattern = /#[0-9a-f]{3,8}\b|rgba?\([^)]*\)/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text))) {
    const value = match[0].replace(/\s+/g, '')
    counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1])
    .map(([value]) => value)
    .slice(0, 6)
}

/* ── 选择器 → 可渲染样本 ──────────────────────────────────────────────── */

const CLASS_PART = /^\.[A-Za-z_][\w-]*(\.[A-Za-z_][\w-]*)*$/

function classesOf(part: string): string[] {
  return part.split('.').filter(Boolean)
}

/** 依据类名猜标签：表单类给 input，按钮给 button，其余用 div 承载。 */
function tagFor(classes: string[]): { tag: string; attrs: string; text: string } {
  const joined = classes.join(' ')
  if (classes.some(name => /input|field|textarea/.test(name))) {
    return { tag: 'input', attrs: ' type="text" placeholder="输入内容" value=""', text: '' }
  }
  if (classes.some(name => /button|btn/.test(name))) {
    return { tag: 'button', attrs: ' type="button"', text: '按钮' }
  }
  if (classes.some(name => /thumb|cover|image|avatar|preview|swatch/.test(name))) {
    return { tag: 'div', attrs: '', text: '' }
  }
  if (classes.some(name => /icon|dot|badge|mark/.test(name))) {
    return { tag: 'span', attrs: '', text: '●' }
  }
  return { tag: 'div', attrs: '', text: sampleText(classes) }
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
}

/** 一条只由类名组成的后代选择器 → 嵌套标签；不满足条件的返回 null。 */
export function selectorToHtml(selector: string): string | null {
  const parts = selector.trim().split(/\s+/)
  if (parts.length === 0 || parts.length > 4) return null
  if (!parts.every(part => CLASS_PART.test(part))) return null
  const build = (depth: number): string => {
    const part = parts[depth]
    const classes = classesOf(part)
    const { tag, attrs, text } = tagFor(classes)
    const open = `<${tag} class="${escapeAttribute(classes.join(' '))}"${attrs}>`
    const close = tag === 'input' ? '' : `</${tag}>`
    const inner = depth === parts.length - 1 ? text : build(depth + 1)
    return `${open}${inner}${close}`
  }
  let markup = build(0)
  if (parts.length === 1) return markup
  // 祖先那层自己可能是 flex 容器（例如 .library-surface 是纵向 flex），
  // 样本直接当它的子元素时，原本按宽度写的 flex-basis 会变成高度。
  // 在祖先与样本之间垫一层块级宿主，把两边的布局隔开，选择器照样匹配。
  // 同时给祖先打一个显式标记：舞台只清这一层的视觉，样本自己一个字都不改。
  markup = markup.replace(/^<div class="([^"]*)"/, '<div class="$1 style-chain-anchor"')
  const open = markup.indexOf('>') + 1
  const close = markup.lastIndexOf('</')
  return `${markup.slice(0, open)}<div class="style-specimen-host">${markup.slice(open, close)}</div>${markup.slice(close)}`
}

/** 规则体越像一块「界面表面」，越适合当样本；纯定位与隐藏的规则排后面。 */
function specimenScore(rule: CssRule): number {
  const body = rule.body.toLowerCase()
  let score = 0
  if (body.includes('background')) score += 3
  if (body.includes('border')) score += 2
  if (body.includes('padding')) score += 1
  if (body.includes('border-radius')) score += 2
  if (body.includes('font-size')) score += 1
  if (body.includes('display: none')) score -= 6
  if (body.includes('position: absolute')) score -= 2
  if (body.includes('position: fixed')) score -= 4
  if (body.includes('z-index')) score -= 2
  return score
}

export function buildSpecimens(rules: CssRule[], limit: number): StyleSpecimen[] {
  const seen = new Set<string>()
  const candidates: Array<StyleSpecimen & { score: number }> = []
  for (const rule of rules) {
    const html = selectorToHtml(rule.selector)
    if (!html || seen.has(html)) continue
    seen.add(html)
    candidates.push({ selector: rule.selector.trim(), html, score: specimenScore(rule) })
  }
  return candidates
    .sort((left, right) => right.score - left.score)
    .slice(0, limit)
    .map(({ selector, html }) => ({ selector, html }))
}

/* ── 汇总 ──────────────────────────────────────────────────────────────── */

function readPurpose(css: string): string {
  // 文件头可能先写一条 user: 注释，再写真正的说明；所以把第一条规则之前的所有注释都翻一遍。
  const head = css.slice(0, 2400)
  const stop = head.indexOf('{')
  const region = stop === -1 ? head : head.slice(0, stop)
  const blocks = region.match(/\/\*[\s\S]*?\*\//g) ?? []
  const candidates: string[] = []
  for (const block of blocks) {
    // user: 注释整块跳过：它的续行同样是需求原文，不该被当成这份样式的说明。
    if (/^\s*\*?\s*user:/.test(block.replace(/^\/\*+/, ''))) continue
    const lines = block
      .replace(/^\/\*|\*\/$/g, '')
      .split('\n')
      .map(line => line.replace(/^\s*\*?\s?/, '').trim())
      .filter(line => line.length > 4 && !/^[=\-*#_]+$/.test(line))
    for (const line of lines) {
      if (line.startsWith('user:') || line.startsWith('来源') || line.startsWith('Source')) continue
      candidates.push(line.replace(/[。.]$/, ''))
    }
  }
  // 一句说明里夹几个中文不算中文说明：按汉字数量挑，够了才用，否则退回第一句。
  const scored = candidates.map(line => ({ line, cjk: (line.match(/[\u4e00-\u9fa5]/g) ?? []).length }))
  const best = scored.reduce((top, item) => (item.cjk > top.cjk ? item : top), { line: '', cjk: 0 })
  const chosen = best.cjk >= 6 ? best.line : (candidates[0] ?? '')
  return chosen.slice(0, 120)
}

function countClasses(rules: CssRule[]): number {
  const names = new Set<string>()
  for (const rule of rules) {
    const matches = rule.selector.match(/\.[A-Za-z_][\w-]*/g)
    if (!matches) continue
    for (const name of matches) names.add(name)
  }
  return names.size
}

function categoryOf(file: string): StyleAssetCategory {
  return CATALOG[file.split('/').pop() ?? '']?.category ?? 'shell'
}

function nameOf(file: string): string {
  const base = file.split('/').pop() ?? file
  return CATALOG[base]?.name ?? base.replace(/\.css$/, '')
}

function normalizeFile(path: string): string {
  return path.replace(/^\.\.\//, '').replace(/^\.\//, '')
}

function parseAsset(path: string, raw: string, index: number): StyleAsset {
  const file = normalizeFile(path)
  const rules = collectRules(raw)
  const tokens = collectTokens(raw)
  const specimen = buildSpecimens(rules, 24)
  const preview = specimen
    .slice(0, 3)
    .map(item => `<div class="style-specimen-item">${item.html}</div>`)
    .join('')
  return {
    id: `style-${index}-${file.replace(/[^\w]+/g, '-')}`,
    name: nameOf(file),
    file,
    category: categoryOf(file),
    purpose: readPurpose(raw),
    lines: raw.split('\n').length,
    ruleCount: rules.length,
    tokenCount: tokens.length,
    classCount: countClasses(rules),
    tokens,
    palette: collectPalette(raw),
    specimen,
    preview,
    raw,
  }
}

let cache: StyleAsset[] | null = null

/** 全部样式资产，按「由底层到界面」的顺序排：令牌在前，插件与桌宠在后。 */
export function loadStyleAssets(): StyleAsset[] {
  if (cache) return cache
  const merged = { ...STYLE_MODULES, ...EXTRA_MODULES }
  const entries = Object.entries(merged).sort((left, right) => {
    const leftFile = normalizeFile(left[0])
    const rightFile = normalizeFile(right[0])
    const leftCategory = CATEGORY_ORDER.indexOf(categoryOf(leftFile))
    const rightCategory = CATEGORY_ORDER.indexOf(categoryOf(rightFile))
    if (leftCategory !== rightCategory) return leftCategory - rightCategory
    return leftFile.localeCompare(rightFile)
  })
  cache = entries.map(([path, raw], index) => parseAsset(path, raw, index))
  return cache
}

export function categoryLabel(category: StyleAssetCategory): string {
  return CATEGORY_LABEL[category] ?? '其他'
}

/** 分类按资产里实际出现的顺序给出，工具栏只列有内容的类别。 */
export function styleCategories(assets: StyleAsset[]): Array<{ id: StyleAssetCategory; label: string; count: number }> {
  const counts = new Map<StyleAssetCategory, number>()
  for (const asset of assets) counts.set(asset.category, (counts.get(asset.category) ?? 0) + 1)
  return CATEGORY_ORDER
    .filter(category => counts.has(category))
    .map(category => ({ id: category, label: CATEGORY_LABEL[category], count: counts.get(category) ?? 0 }))
}
