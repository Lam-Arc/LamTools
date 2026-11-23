// user:“地址栏下方出现 [object Object] 文本”+(原生浏览器命令失败时 reject 的是一个对象
//  `{code, message, retriable}`（Rust 的 BrowserError 就是这么序列化的），
//  任何地方写 String(错误) 都只会得到 "[object Object]" —— 所以前端只允许经过这里取一句人话)。
//
// 这条规则的边界写死在三处：
//  1) 字符串原样返回（Rust 的 message 本来就是中文人话）；
//  2) 对象/Error 一律取 `.message`，取不到再按 `code` 翻成人话，最后才用兜底句；
//  3) 协议噪声（"failed to invoke …"、"[object Object]"）不直接显示给用户。

/** 原生失败的可读文本来源；与 Rust `BrowserError` 同形，但不假设一定完整。 */
export interface BrowserFailure {
  code?: unknown
  message?: unknown
  retriable?: unknown
  host?: unknown
}

/** 错误码 → 一句能照着做的话。没有对应码时由 message 自己说话。 */
const CODE_TEXT: Record<string, string> = {
  tab_inactive: '这个标签现在在后台，切回来再试一次',
  tab_not_found: '这个浏览器标签已经关闭',
  tab_exists: '这个浏览器标签已经打开',
  invalid_bounds: '网页区域无效，挪一下窗口再试一次',
  invalid_url: '请输入网址或搜索内容',
  blocked_scheme: '这个地址不能用内置浏览器打开',
  temporary_session_unavailable: '临时会话在本版本不可用',
  permission_denied: '这个授权请求不属于当前标签',
  internal: '浏览器内部出错了',
  unsupported: '这个操作暂不支持',
}

function textOf(value: unknown, depth = 0): string {
  if (depth > 3) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (!value || typeof value !== 'object') return ''
  // Error 与 Rust 的失败对象都有 message：取它，别把整个对象变成字符串。
  const message = (value as { message?: unknown }).message
  if (message !== undefined && message !== value) return textOf(message, depth + 1)
  return ''
}

/** 从失败值里取出错误码（`Error` 没有 code；Rust 失败对象有）。 */
export function errorCode(value: unknown): string {
  if (!value || typeof value !== 'object') return ''
  const code = (value as { code?: unknown }).code
  return typeof code === 'string' ? code : ''
}

/** 协议层噪声：这类文字不是给用户看的，宁可换成码对应的说明或兜底句。 */
function protocolNoise(text: string): boolean {
  if (!text) return true
  if (text.includes('[object Object]')) return true
  return /^(failed to (invoke|call|execute|load|send)\b)/i.test(text)
}

/**
 * 任何失败值 → 一句可读的中文。
 * user:“失败时给出可读原因（不是静默、不是 [object Object]、不是英文协议原文）”+
 * (顺序是「真消息 → 错误码对应的说明 → 兜底句」；调用方只负责决定兜底句说什么)。
 */
export function errorText(value: unknown, fallback = '操作没有完成，请再试一次'): string {
  const message = textOf(value)
  if (!protocolNoise(message)) return message
  const mapped = CODE_TEXT[errorCode(value)]
  if (mapped) return mapped
  if (message && !protocolNoise(message)) return message
  return fallback
}

/** 失败是否可重试：Rust 明确给了 retriable 就听它，对象形态的兜底当作不可重试。 */
export function errorRetriable(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  return (value as BrowserFailure).retriable === true
}
