/**
 * Assistant 展示层气泡拆分。
 *
 * user:“支持开启或关闭自动气泡拆分”+(把一条回复切成多个气泡只是展示行为，
 * 不改变消息协议与上下文：宿主仍是一条消息、一份 parts，会话历史不动)。
 *
 * 两层来源：
 *  1. 模型显式标记（后端用轻量提示词要求输出 `<<<BUBBLE>>>`）：命中即开下一个气泡，
 *     标记本身不进入渲染。
 *  2. 客户端结构兜底：分隔线、二三级标题、超过字符预算的空行段落。兜底不引入
 *     任何模型/向量依赖，纯文本扫描。
 *
 * 保护完整结构：围栏代码块、展示公式块（$$ / \[ / \begin{env}）、表格行一律整段
 * 保留，绝不在其中拆分。
 */

/** 模型侧拆分标记：独占一行或夹在行内皆可，渲染时一定被吃掉。 */
export const ASSISTANT_BUBBLE_MARKER = '<<<BUBBLE>>>'

/** 结构兜底的段落软预算：气泡内累计超过这个字数才在空行处另起气泡。 */
const STRUCTURAL_BUBBLE_BUDGET = 320

export interface AssistantBubbleSplitOptions {
  /** 显式标记字符串，默认 ASSISTANT_BUBBLE_MARKER。 */
  marker?: string
  /** 结构兜底开关；关闭时只认模型标记。 */
  structural?: boolean
  /** 流式输出中：末尾未写完的标记先隐藏，避免闪出一截裸标记。 */
  streaming?: boolean
  /** 结构兜底的字符预算（最小 160）。 */
  budget?: number
}

export interface AssistantBubble {
  /** 位置稳定的 key：内容变化只换文本，不重建节点。 */
  key: string
  content: string
}

type SplitLine = string[]

/**
 * 只裁掉气泡首尾的空行：代码块内部的空行、行尾空格都属于内容，绝不动。
 */
function normalizeBlock(text: string): string {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  let start = 0
  let end = lines.length
  while (start < end && lines[start].trim() === '') start += 1
  while (end > start && lines[end - 1].trim() === '') end -= 1
  return lines.slice(start, end).join('\n')
}

function matchOpenFence(line: string): { char: string; length: number } | null {
  const match = /^\s{0,3}(`{3,}|~{3,})/.exec(line)
  if (!match) return null
  return { char: match[1][0], length: match[1].length }
}

function isClosingFence(trimmed: string, fence: { char: string; length: number }): boolean {
  if (!trimmed || trimmed.length < fence.length) return false
  for (const char of trimmed) {
    if (char !== fence.char) return false
  }
  return true
}

/**
 * 展示公式块的开闭判定。返回关闭标记；单行公式返回 null（该行本身仍整体保护）。
 */
function mathBlockClose(trimmed: string): string | null {
  if (trimmed.startsWith('$$')) {
    if (trimmed.length > 4 && trimmed.endsWith('$$')) return null
    return '$$'
  }
  if (trimmed.startsWith('\\[')) {
    return trimmed.endsWith('\\]') ? null : '\\]'
  }
  const begin = /^\\begin\{([a-zA-Z*]+)\}/.exec(trimmed)
  if (begin) return `\\end{${begin[1]}}`
  return null
}

function isTableLine(trimmed: string): boolean {
  return trimmed.startsWith('|')
}

function isHorizontalRule(trimmed: string): boolean {
  return /^(?:-[ \t]*){3,}$/.test(trimmed)
    || /^(?:\*[ \t]*){3,}$/.test(trimmed)
    || /^(?:_[ \t]*){3,}$/.test(trimmed)
}

function isSectionHeading(trimmed: string): boolean {
  return /^#{2,3}[ \t]+\S/.test(trimmed)
}

/**
 * 按标记切一行；行内代码（反引号未闭合）里的同名文字不算拆分信号。
 */
function splitByMarker(line: string, marker: string): string[] {
  if (!marker || !line.includes(marker)) return [line]
  const segments: string[] = []
  let rest = line
  let guard = 0
  while (rest.includes(marker) && guard < 64) {
    const index = rest.indexOf(marker)
    const before = rest.slice(0, index)
    if ((before.match(/`/g)?.length ?? 0) % 2 === 1) break
    segments.push(before)
    rest = rest.slice(index + marker.length)
    guard += 1
  }
  segments.push(rest)
  return segments
}

function stripPartialMarker(text: string, marker: string): string {
  if (!marker) return text
  for (let length = marker.length - 1; length > 1; length -= 1) {
    if (text.endsWith(marker.slice(0, length))) return text.slice(0, text.length - length).trimEnd()
  }
  return text
}

/**
 * 把一条 Assistant 回复切成若干气泡。空文本返回空数组；无可拆点时返回单气泡。
 */
export function splitAssistantBubbles(text: string, options: AssistantBubbleSplitOptions = {}): AssistantBubble[] {
  const source = String(text ?? '')
  if (!source.trim()) return []
  const marker = (options.marker ?? ASSISTANT_BUBBLE_MARKER).trim()
  const structural = options.structural === true
  const streaming = options.streaming === true
  const budget = Math.max(160, Number(options.budget) || STRUCTURAL_BUBBLE_BUDGET)

  const blocks: SplitLine[] = [[]]
  let fence: { char: string; length: number } | null = null
  let mathClose: string | null = null

  const currentBlock = () => blocks[blocks.length - 1]
  const hasContent = () => currentBlock().join('\n').trim().length > 0
  const blockLength = () => currentBlock().join('\n').trim().length
  const pushLine = (line: string) => { currentBlock().push(line) }
  const startBubble = () => {
    if (!hasContent()) return
    blocks.push([])
  }

  for (const line of source.replace(/\r\n?/g, '\n').split('\n')) {
    const trimmed = line.trim()

    // 围栏代码块内：整段保留，不做任何拆分
    if (fence) {
      pushLine(line)
      if (isClosingFence(trimmed, fence)) fence = null
      continue
    }
    // 展示公式块内：整段保留
    if (mathClose) {
      pushLine(line)
      if (trimmed.endsWith(mathClose)) mathClose = null
      continue
    }

    const openedFence = matchOpenFence(line)
    if (openedFence) {
      fence = openedFence
      pushLine(line)
      continue
    }

    const closedMath = mathBlockClose(trimmed)
    if (closedMath) {
      mathClose = closedMath
      pushLine(line)
      continue
    }
    // 单行公式（$$…$$、\[…\]）：整行保留
    if (trimmed.startsWith('$$') || trimmed.startsWith('\\[') || trimmed.startsWith('\\begin{')) {
      pushLine(line)
      continue
    }

    // 表格：只保证不被拆，不参与拆分
    if (isTableLine(trimmed)) {
      pushLine(line)
      continue
    }

    // 模型显式标记：命中即开下一个气泡，标记本身不展示
    const segments = splitByMarker(line, marker)
    if (segments.length > 1) {
      segments.forEach((segment, index) => {
        if (index > 0) startBubble()
        pushLine(segment)
      })
      continue
    }

    if (structural) {
      // 分隔线本身是排版分隔，吞掉并在处另起气泡
      if (isHorizontalRule(trimmed)) {
        startBubble()
        continue
      }
      if (isSectionHeading(trimmed) && hasContent()) {
        startBubble()
        pushLine(line)
        continue
      }
      // 空行且当前气泡已超预算：在此分段（空行不再留给下一个气泡）
      if (trimmed === '' && hasContent() && blockLength() >= budget) {
        startBubble()
        continue
      }
    }

    pushLine(line)
  }

  const bubbles = blocks
    .map((lines, index) => ({ index, content: normalizeBlock(lines.join('\n')) }))
    .filter(bubble => bubble.content !== '')

  if (bubbles.length === 0) return []
  if (streaming) {
    const last = bubbles[bubbles.length - 1]
    last.content = stripPartialMarker(last.content, marker)
    if (!last.content.trim()) bubbles.pop()
  }

  return bubbles.map((bubble, index) => ({
    key: `assistant-bubble-${bubble.index}-${index}`,
    content: bubble.content,
  }))
}
