/**
 * 会话内「过程行」的语义图标映射。
 *
 * user:“废弃通用的扳手（Wrench）图标，所有内置及系统级能力必须映射至语义明确的专属图标
 * （建议统一使用 16px × 16px 线性图标，线条粗细 1.5px~1.75px）”
 * +（把「这一步在干什么」从工具名字符串里解析成稳定的语义类别，再由类别决定专属图标与线宽；
 * 识别逻辑抽成纯函数，不依赖 Vue，方便直接单测。无法识别时统一落到 generic，
 * 绝不再回退扳手。）
 */
import {
  AppWindow,
  BookOpen,
  Bot,
  Brain,
  CircleHelp,
  Code2,
  Database,
  Download,
  FileCode,
  FileOutput,
  FileSearch,
  FileText,
  GitBranch,
  Globe,
  Image,
  Inbox,
  Link,
  ListTree,
  MonitorSmartphone,
  Palette,
  Plug,
  Power,
  PowerOff,
  Search,
  Send,
  Sparkles,
  Table,
  Terminal,
  UserRoundPlus,
  Wand2,
  type LucideIcon,
} from 'lucide-vue-next'

export type ProcessIconKind =
  | 'reasoning'
  | 'planning'
  | 'file-read'
  | 'file-write'
  | 'memory'
  | 'code'
  | 'search'
  | 'web'
  | 'image'
  | 'question'
  | 'subagent'
  | 'computer'
  | 'mcp'
  | 'generic'

export interface ProcessIconInput {
  partType?: string
  toolName?: string
  label?: string
  args?: unknown
  result?: unknown
}

/** 文件类再按后缀细分，决定用表格 / 代码 / 图片 / 文本 / 通用文件图标。 */
type ProcessFileCategory = 'table' | 'code' | 'image' | 'text' | 'plain'

// ---------------------------------------------------------------------------
// 后缀细分
// ---------------------------------------------------------------------------

// user:“读取/解析文件：FileSearch / FileText（按后缀细分：表格 Table、代码 FileCode、图片 Image）”
// +（同一个「读文件」语义，后缀不同就看得出是表格还是代码还是图片。）
const EXTENSION_CATEGORY: Record<string, ProcessFileCategory> = {
  csv: 'table', tsv: 'table', xlsx: 'table', xls: 'table', xlsm: 'table',
  parquet: 'table', ods: 'table', numbers: 'table',
  ts: 'code', tsx: 'code', js: 'code', jsx: 'code', mjs: 'code', cjs: 'code',
  vue: 'code', svelte: 'code', py: 'code', rs: 'code', go: 'code', java: 'code',
  kt: 'code', swift: 'code', c: 'code', h: 'code', cc: 'code', cpp: 'code',
  hpp: 'code', cs: 'code', rb: 'code', php: 'code', sh: 'code', bash: 'code',
  zsh: 'code', ps1: 'code', sql: 'code', lua: 'code', json: 'code',
  yml: 'code', yaml: 'code', toml: 'code', xml: 'code', css: 'code', scss: 'code',
  png: 'image', jpg: 'image', jpeg: 'image', webp: 'image', gif: 'image',
  svg: 'image', bmp: 'image', ico: 'image', avif: 'image', tiff: 'image', heic: 'image',
  txt: 'text', md: 'text', markdown: 'text', log: 'text', rst: 'text',
  pdf: 'text', doc: 'text', docx: 'text', ppt: 'text', pptx: 'text',
}

/** 可能承载文件路径的入参字段，顺序即优先级。 */
const PATH_KEYS = [
  'path', 'file', 'file_path', 'filepath', 'filename', 'target',
  'output', 'destination', 'source', 'uri',
]

function recordOf(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text.startsWith('{')) return {}
    try {
      const parsed: unknown = JSON.parse(text)
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? parsed as Record<string, unknown>
        : {}
    } catch {
      return {}
    }
  }
  return {}
}

function extensionOf(candidate: string): string {
  const base = String(candidate || '').split(/[?#]/, 1)[0]!.split(/[\\/]/).pop() || ''
  const dot = base.lastIndexOf('.')
  return dot > 0 && dot < base.length - 1 ? base.slice(dot + 1).toLowerCase() : ''
}

/**
 * 从入参 / 标题 / 结果里捞出最像文件路径的那一段。
 * 先看结构化入参，再从可读标题里抓「带后缀的片段」，最后才看结果文本。
 */
function fileCandidate(input: ProcessIconInput): string {
  const args = recordOf(input.args)
  for (const key of PATH_KEYS) {
    const value = args[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  if (typeof input.args === 'string' && input.args.trim() && !input.args.trim().startsWith('{')) {
    return input.args.trim()
  }
  const withExtension = /[\w./\\-]+\.[A-Za-z0-9]{1,8}\b/
  const label = String(input.label || '')
  const fromLabel = label.match(withExtension)
  if (fromLabel) return fromLabel[0]
  const fromResult = String(input.result ?? '').match(withExtension)
  return fromResult ? fromResult[0] : ''
}

function fileCategory(input: ProcessIconInput): ProcessFileCategory {
  return EXTENSION_CATEGORY[extensionOf(fileCandidate(input))] || 'plain'
}

// ---------------------------------------------------------------------------
// 语义识别
// ---------------------------------------------------------------------------

// 部分 partType 本身就说明语义，比工具名更可靠，优先采信。
const KIND_BY_PART_TYPE: Record<string, ProcessIconKind> = {
  reasoning: 'reasoning',
  // 上下文压缩属于「记忆」类系统能力。
  compaction: 'memory',
  plan: 'planning',
  todo_update: 'planning',
  decision: 'question',
  questiongroup: 'question',
  sub_line: 'subagent',
  agent_summary: 'subagent',
  file_diff: 'file-write',
  command_output: 'code',
  attachment: 'file-read',
}

// user:“所有内置及系统级能力必须映射至语义明确的专属图标”+(系统级能力不再落 generic：
// MCP 工具走 mcp，桌面/手机操控与窗口级动作走 computer)。
const MCP_NAME = /^mcp/
// 桌面/手机操控：computer_use、android_use、desktop_overlay、截图、Ping、鼠标键盘、窗口、点击、输入、滚动。
// ping 加前置边界，避免 mapping / copying 这类无关名字被吞进来。
const COMPUTER_NAME = /computer|android|desktop|overlay|screen|(^|[^a-z])ping|mouse|keyboard|window|click|type_text|scroll/

// 子代理事件：创建 / 启用 / 关闭 / 发消息 / 收消息，视觉上仍要能分得出来。
const SUB_AGENT_NAME = /sub[_-]?agent|delegate|spawn/
const MEMORY_NAME = /memory|remember|recall|context|library|skill|knowledge|rag/
const IMAGE_NAME = /image|imagine|draw|paint|palette|upscale|inpaint|diffus|t2i|i2i/
const CHECKLIST_NAME = /checklist|todo|task_plan|\bplan\b/
// 注意：工具名里常出现下划线（npm_install / ask_user），所以这里不用 \b，
// 否则 `_` 属于单词字符会让词边界失效，规则静默漏掉整类工具。
// user:“代码解释器/沙盒：Terminal / Code2”+(命令行执行与代码解释器同属执行类语义)。
const CODE_NAME = /command|shell|exec|bash|powershell|terminal|npm|node|python|sandbox|interpreter|repl|process|kill|deno|bun/
// user:“联网搜索：Globe / Search；网页抓取/浏览器：AppWindow / Link”+(检索与抓取分开识别)。
const SEARCH_NAME = /grep|rg|glob|find|search|query|lookup/
const WEB_NAME = /fetch|browser|http|web|url|link|crawl|scrape|curl|wget/
const FILE_WRITE_NAME = /write|edit|patch|apply|create|delete|remove|move|rename|mkdir|touch|save|export|download|copy|output/
const FILE_READ_NAME = /read|\bcat\b|open|get.?content|view|show|\bhead\b|\btail\b|stat|list|\bls\b|\bdir\b|attach|preview|inspect|peek/
const GIT_NAME = /git|commit|branch|merge|push|pull|checkout|rebase|stash/
const QUESTION_NAME = /question|ask|decision|confirm|approve|clarify|prompt/
const PLAN_NAME = /decompose|subtask|schedule|step/

function processName(input: ProcessIconInput): string {
  return String(input.toolName || input.label || '').trim().toLowerCase()
}

type SubAgentEvent = 'created' | 'enabled' | 'closed' | 'message_sent' | 'message_received' | ''

function subAgentEventOf(input: ProcessIconInput): SubAgentEvent {
  const name = processName(input)
  if (name === 'sub_agent_message' || name === 'sub_agent_send') return 'message_sent'
  if (name === 'sub_agent_receive') return 'message_received'
  const args = recordOf(input.args)
  const result = recordOf(input.result)
  const action = String(args.action || result.action || '').toLowerCase()
  const lifecycle = String(
    result.lifecycle_action || result.lifecycleAction || args.lifecycle_action || args.lifecycleAction || '',
  ).toLowerCase()
  if (action === 'close' || action === 'closed' || lifecycle === 'closed') return 'closed'
  if (lifecycle === 'enabled' || lifecycle === 'reopened') return 'enabled'
  if (action === 'create' || action === 'created' || lifecycle === 'created') return 'created'
  if (action === 'send' || action === 'sent' || action === 'message_sent') return 'message_sent'
  if (action === 'receive' || action === 'received' || action === 'message_received') return 'message_received'
  return ''
}

/**
 * 把一条过程行解析成语义类别。
 * 顺序即优先级：partType 先于工具名，记忆先于检索（search_context 属于记忆），
 * 检索先于抓取（web_search 属于联网搜索），抓取先于读文件（open_url 不是读文件）。
 */
export function resolveProcessIconKind(input: ProcessIconInput = {}): ProcessIconKind {
  const partType = String(input.partType || '').trim().toLowerCase()
  const byPartType = KIND_BY_PART_TYPE[partType]
  if (byPartType) return byPartType

  const name = processName(input)
  if (!name) return 'generic'

  // mcp__ 前缀必须最先判定：否则 mcp__filesystem__read_file 会被读文件规则吃掉。
  if (MCP_NAME.test(name)) return 'mcp'
  // 系统级操控也要早于读/写类：type_text、window、scroll 不能被 read/write 抢走。
  if (COMPUTER_NAME.test(name)) return 'computer'
  if (SUB_AGENT_NAME.test(name)) return 'subagent'
  if (MEMORY_NAME.test(name)) return 'memory'
  if (IMAGE_NAME.test(name)) return 'image'
  if (CHECKLIST_NAME.test(name)) return 'planning'
  if (CODE_NAME.test(name)) return 'code'
  // git 必须早于读文件规则：git_status 里的 stat 否则会被当成读文件。
  if (GIT_NAME.test(name)) return 'code'
  if (SEARCH_NAME.test(name)) return 'search'
  if (WEB_NAME.test(name)) return 'web'
  if (FILE_WRITE_NAME.test(name)) return 'file-write'
  if (FILE_READ_NAME.test(name)) return 'file-read'
  if (QUESTION_NAME.test(name)) return 'question'
  if (PLAN_NAME.test(name)) return 'planning'
  return 'generic'
}

// ---------------------------------------------------------------------------
// 类别 → 图标 / 线宽
// ---------------------------------------------------------------------------

const FILE_READ_ICONS: Record<ProcessFileCategory, LucideIcon> = {
  table: Table,
  code: FileCode,
  image: Image,
  text: FileText,
  plain: FileSearch,
}

// user:“生成/导出文件：FileOutput / Download”+(写出文件用输出图标，下载动作另给下载图标)。
const FILE_WRITE_ICONS: Record<ProcessFileCategory, LucideIcon> = {
  table: Table,
  code: FileCode,
  image: Image,
  text: FileOutput,
  plain: FileOutput,
}

// user:“统一使用 16px × 16px 线性图标，线条粗细 1.5px~1.75px”
// +（笔画密的图标略细、笔画少的略粗，全部落在 1.5~1.75 之间。）
const STROKE_BY_KIND: Record<ProcessIconKind, number> = {
  reasoning: 1.6,
  planning: 1.6,
  'file-read': 1.6,
  'file-write': 1.6,
  memory: 1.5,
  code: 1.5,
  search: 1.7,
  web: 1.6,
  image: 1.6,
  question: 1.7,
  subagent: 1.5,
  computer: 1.6,
  mcp: 1.6,
  generic: 1.5,
}

function subAgentIcon(input: ProcessIconInput): LucideIcon {
  switch (subAgentEventOf(input)) {
    case 'created': return UserRoundPlus
    case 'enabled': return Power
    case 'closed': return PowerOff
    case 'message_sent': return Send
    case 'message_received': return Inbox
    default: return Bot
  }
}

/**
 * 语义类别 → 具体图标。
 *
 * user:“废弃通用的扳手（Wrench）图标”+(没有任何一条分支会返回 Wrench；
 * 认不出来的一律走 generic 的 Sparkles，绝不回退扳手)。
 *
 * 第二个参数可选：同一类别下按工具名/文件后缀再细分（文件读写、git、联网搜索、
 * 网页抓取、图像编辑、子代理事件），不传时返回该类别的默认图标。
 */
export function processIconComponent(kind: ProcessIconKind, input: ProcessIconInput = {}): LucideIcon {
  const name = processName(input)
  switch (kind) {
    case 'reasoning':
      return Brain
    case 'planning':
      return ListTree
    case 'file-read':
      return FILE_READ_ICONS[fileCategory(input)]
    case 'file-write':
      return /download|export/.test(name) ? Download : FILE_WRITE_ICONS[fileCategory(input)]
    case 'memory':
      return /library|skill|knowledge|book/.test(name) ? BookOpen : Database
    case 'code':
      if (GIT_NAME.test(name)) return GitBranch
      if (/python|sandbox|interpreter|\brepl\b|\bcode\b|eval/.test(name)) return Code2
      return Terminal
    case 'search':
      // 联网搜索给 Globe，本地检索给放大镜（不用 \b，web_search 里 web 后面就是下划线）。
      return /web|internet|online/.test(name) ? Globe : Search
    case 'web':
      return /\burl\b|link|open/.test(name) ? Link : AppWindow
    case 'image':
      return /edit|inpaint|upscale|remove|retouch/.test(name) ? Wand2 : Palette
    case 'question':
      return CircleHelp
    case 'subagent':
      return subAgentIcon(input)
    // user:“所有内置及系统级能力必须映射至语义明确的专属图标”+(桌面/手机操控给屏幕图标，
    // MCP 工具给插头图标，两者都不再借通用兜底。)
    case 'computer':
      return MonitorSmartphone
    case 'mcp':
      return Plug
    case 'generic':
      return Sparkles
    default:
      return Sparkles
  }
}

/** 该类别的线宽，恒在 1.5~1.75 之间。 */
export function processIconStroke(kind: ProcessIconKind): number {
  return STROKE_BY_KIND[kind] ?? 1.6
}
