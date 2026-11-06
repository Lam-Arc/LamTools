/**
 * Pin 环全局快捷键：把"按下的物理键"翻译成 accelerator 字符串。
 *
 * user:“把桌面端 Pin 环的快捷键设置，从「手动输入字符串」改成「按下物理键录制」”
 * +(用户点一下录制、按一次组合键就完成绑定，不用记 Ctrl+Alt+Space 这种写法，
 * 也不会因为手写错键名导致热键悄悄注册不上。)
 *
 * 翻译规则同时受两处约束：
 * 1) accelerator 的写法（Ctrl / Alt / Shift / Super + Space / F1..F12 / A..Z / 0..9
 *    以及 ArrowUp、Backspace 这类键名），这是 Tauri 的通用写法；
 * 2) 桌面端 core/desktop/src-tauri/src/pet/platform.rs 的 parse_hotkey 真正认得的主键
 *    （SPACE / TAB / ENTER / A-Z / 0-9 / F1-F24）。
 *    桌面端当前不认方向键、Backspace 这类键名，所以录制时直接拒绝并说明，
 *    而不是绑定一个"看起来成功、实际按不出反应"的热键。
 *
 * 本文件只有纯函数，不碰 DOM，不碰配置，便于单测。
 */

/** 规范的修饰键顺序，与默认值 Ctrl+Alt+Space 一致。 */
export const MODIFIER_ORDER = ['Ctrl', 'Alt', 'Shift', 'Super'] as const

export type HotkeyModifier = (typeof MODIFIER_ORDER)[number]

/** 录制时收到的一次按键，字段与 KeyboardEvent 对齐以方便直接传入。 */
export interface HotkeyKeyInput {
  /** KeyboardEvent.key 原值。 */
  key: string
  ctrlKey?: boolean
  shiftKey?: boolean
  altKey?: boolean
  metaKey?: boolean
  /** 长按产生的重复事件。 */
  repeat?: boolean
}

export type HotkeyCaptureResult =
  /** 组合键成立：accelerator 可直接写配置并注册。 */
  | { status: 'captured'; accelerator: string; label: string }
  /** 还差主键（只按了修饰键，或按了锁键）：继续录制。 */
  | { status: 'pending'; hint: string }
  /** Esc：用户取消录制。 */
  | { status: 'cancelled' }
  /** 组合不成立：提示原因，继续录制。 */
  | { status: 'rejected'; reason: string }

/**
 * KeyboardEvent.key → accelerator 键名。
 *
 * 键名一律取 Tauri 支持的写法，不产出浏览器里根本不存在的名字；
 * 认不出来的键返回 null，由调用方按"非法键"处理。
 */
const NAMED_KEY_ALIASES: Record<string, string> = {
  ' ': 'Space',
  space: 'Space',
  spacebar: 'Space',
  tab: 'Tab',
  enter: 'Enter',
  return: 'Enter',
  backspace: 'Backspace',
  delete: 'Delete',
  del: 'Delete',
  insert: 'Insert',
  home: 'Home',
  end: 'End',
  pageup: 'PageUp',
  pagedown: 'PageDown',
  arrowup: 'ArrowUp',
  arrowdown: 'ArrowDown',
  arrowleft: 'ArrowLeft',
  arrowright: 'ArrowRight',
  escape: 'Escape',
  esc: 'Escape',
  backquote: 'Backquote',
  '`': 'Backquote',
  '-': 'Minus',
  minus: 'Minus',
  '=': 'Equal',
  equal: 'Equal',
  '[': 'BracketLeft',
  bracketleft: 'BracketLeft',
  ']': 'BracketRight',
  bracketright: 'BracketRight',
  '\\': 'Backslash',
  backslash: 'Backslash',
  ';': 'Semicolon',
  semicolon: 'Semicolon',
  "'": 'Quote',
  quote: 'Quote',
  ',': 'Comma',
  comma: 'Comma',
  '.': 'Period',
  period: 'Period',
  '/': 'Slash',
  slash: 'Slash',
}

/** 单独按下不算数、但也不该报错的键：修饰键与锁定键。 */
const MODIFIER_KEYS = new Set([
  'control',
  'ctrl',
  'shift',
  'alt',
  'altgraph',
  'meta',
  'os',
  'super',
  'win',
  'fn',
  'capslock',
  'numlock',
  'scrolllock',
])

export function isModifierKey(key: string): boolean {
  return MODIFIER_KEYS.has((key || '').toLowerCase())
}

export function isEscapeKey(key: string): boolean {
  const lower = (key || '').toLowerCase()
  return lower === 'escape' || lower === 'esc'
}

export function translateKeyName(rawKey: string): string | null {
  if (!rawKey) return null
  const alias = NAMED_KEY_ALIASES[rawKey.toLowerCase()]
  if (alias) return alias
  // user:“大小写归一”+(Shift+a 与 a 都记成 A，避免同一组合写出两种字符串。)
  if (/^[a-zA-Z]$/.test(rawKey)) return rawKey.toUpperCase()
  if (/^[0-9]$/.test(rawKey)) return rawKey
  const fn = /^[fF]([1-9]|1[0-9]|2[0-4])$/.exec(rawKey)
  if (fn) return `F${fn[1]}`
  return null
}

/**
 * 桌面端 parse_hotkey 当前能解析的主键。
 *
 * 与 platform.rs 的 vk_for_key 保持一致：SPACE / TAB / ENTER / A-Z / 0-9 / F1-F24。
 * 改这里之前先确认桌面端能解析，否则热键会注册失败。
 */
export function isDesktopRegistrableKey(keyName: string): boolean {
  if (keyName === 'Space' || keyName === 'Tab' || keyName === 'Enter') return true
  if (/^[A-Z0-9]$/.test(keyName)) return true
  return /^F([1-9]|1[0-9]|2[0-4])$/.test(keyName)
}

/**
 * Sunday 自己已经占用的组合键：录到直接拒绝，不允许绑成 Ping 环热键。
 *
 * user:“Ctrl+K 是全局搜索，Ctrl+Alt+Shift+R 会清主题并重载页面，这两个组合请直接拒绝”
 * +(绑上去一次按键会同时触发搜索/重置和 Ping 环，用户会以为界面疯了。)
 */
export const RESERVED_ACCELERATORS: readonly string[] = ['Ctrl+K', 'Ctrl+Alt+Shift+R']

export const RESERVED_HOTKEY_REASON = '该组合已被 Sunday 占用，请换一个'

/** 判断一个 accelerator 是否落在保留组合里（修饰键顺序与大小写不敏感）。 */
export function isReservedAccelerator(accelerator: string | null | undefined): boolean {
  const text = (accelerator || '').trim()
  if (!text) return false
  const tokens = text.split('+').map(part => part.trim().toLowerCase()).filter(Boolean)
  return RESERVED_ACCELERATORS.some(reserved => {
    const reservedTokens = reserved.split('+').map(part => part.toLowerCase())
    return reservedTokens.length === tokens.length && reservedTokens.every(token => tokens.includes(token))
  })
}

/** 从按键事件里取出修饰键，顺序固定为 Ctrl、Alt、Shift、Super。 */
export function modifiersFrom(input: HotkeyKeyInput): HotkeyModifier[] {
  const pressed: Record<HotkeyModifier, boolean> = {
    Ctrl: input.ctrlKey === true,
    Alt: input.altKey === true,
    Shift: input.shiftKey === true,
    Super: input.metaKey === true,
  }
  return MODIFIER_ORDER.filter(modifier => pressed[modifier])
}

const TOKEN_LABELS: Record<string, string> = {
  ctrl: 'Ctrl',
  control: 'Ctrl',
  alt: 'Alt',
  altgr: 'AltGr',
  shift: 'Shift',
  super: 'Win',
  win: 'Win',
  meta: 'Win',
  command: 'Win',
  cmd: 'Win',
  space: '空格',
  tab: 'Tab',
  enter: 'Enter',
  return: 'Enter',
  backspace: '退格',
  delete: 'Delete',
  insert: 'Insert',
  home: 'Home',
  end: 'End',
  pageup: 'PageUp',
  pagedown: 'PageDown',
  arrowup: '↑',
  arrowdown: '↓',
  arrowleft: '←',
  arrowright: '→',
  escape: 'Esc',
  esc: 'Esc',
}

/** 单个 token 的可读写法。 */
export function hotkeyTokenLabel(token: string): string {
  return TOKEN_LABELS[token.toLowerCase()] ?? token
}

/**
 * accelerator → 给人看的标签。
 *
 * user:“界面上显示可读标签，不要直接显示 accelerator 原文”+(配置里存 Ctrl+Alt+Space，
 * 界面上显示 Ctrl + Alt + 空格，普通用户不需要看懂存储格式。)
 */
export function formatHotkeyLabel(accelerator: string | null | undefined): string {
  const text = (accelerator || '').trim()
  if (!text) return '未设置'
  const tokens = text
    .split('+')
    .map(part => part.trim())
    .filter(Boolean)
  if (tokens.length === 0) return '未设置'
  return tokens.map(hotkeyTokenLabel).join(' + ')
}

/** 录制时"已按住哪些修饰键"的实时提示。 */
export function modifierPreviewLabel(input: HotkeyKeyInput): string {
  const modifiers = modifiersFrom(input)
  if (modifiers.length === 0) return '请按下组合键'
  return `${modifiers.map(hotkeyTokenLabel).join(' + ')} + …`
}

/**
 * 一次按键 → 录制结果。
 *
 * 只有"至少一个修饰键 + 一个普通键"才算绑定完成：
 * 单个字母若被允许注册成全局热键，用户平时打字就会被吞掉。
 */
export function captureHotkey(input: HotkeyKeyInput): HotkeyCaptureResult {
  const key = typeof input.key === 'string' ? input.key : ''
  // Esc 永远先当取消处理，即使同时按着 Ctrl / Alt。
  if (isEscapeKey(key)) return { status: 'cancelled' }
  if (input.repeat === true) return { status: 'pending', hint: '请按下组合键' }
  if (isModifierKey(key)) return { status: 'pending', hint: modifierPreviewLabel(input) }

  const modifiers = modifiersFrom(input)
  if (modifiers.length === 0) {
    return {
      status: 'rejected',
      reason: '请按住 Ctrl / Alt / Shift / Win 起手，单独一个键会抢走普通打字',
    }
  }

  const keyName = translateKeyName(key)
  if (!keyName) {
    return { status: 'rejected', reason: `不支持的按键：${key || '无法识别'}` }
  }
  if (!isDesktopRegistrableKey(keyName)) {
    return {
      status: 'rejected',
      reason: `桌面端暂不支持 ${hotkeyTokenLabel(keyName)} 做全局热键，请换字母、数字、F1–F12、空格、Tab 或 Enter`,
    }
  }

  const accelerator = [...modifiers, keyName].join('+')
  if (isReservedAccelerator(accelerator)) {
    return { status: 'rejected', reason: RESERVED_HOTKEY_REASON }
  }
  return { status: 'captured', accelerator, label: formatHotkeyLabel(accelerator) }
}
