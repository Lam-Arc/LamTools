/**
 * File-type badge data shared by the composer tokens, message links and the
 * outcome list. The badge is a small rounded square (30% radius) with the
 * extension label, matching the editor-style file icons used elsewhere.
 */

export interface FileTypeBadgeData {
  /** Short label shown inside the badge (1–3 characters). */
  label: string
  /** Badge background colour. */
  background: string
  /** Badge label colour. */
  color: string
}

interface BadgeStyle {
  label: string
  background: string
  color: string
}

const STYLES: Record<string, BadgeStyle> = {
  ts: { label: 'TS', background: '#3178C6', color: '#FFFFFF' },
  tsx: { label: 'TS', background: '#3178C6', color: '#FFFFFF' },
  mts: { label: 'TS', background: '#3178C6', color: '#FFFFFF' },
  cts: { label: 'TS', background: '#3178C6', color: '#FFFFFF' },
  js: { label: 'JS', background: '#F7DF1E', color: '#1C1C1C' },
  jsx: { label: 'JS', background: '#F7DF1E', color: '#1C1C1C' },
  mjs: { label: 'JS', background: '#F7DF1E', color: '#1C1C1C' },
  cjs: { label: 'JS', background: '#F7DF1E', color: '#1C1C1C' },
  vue: { label: 'V', background: '#41B883', color: '#FFFFFF' },
  css: { label: 'CSS', background: '#6F42C1', color: '#FFFFFF' },
  scss: { label: 'CSS', background: '#C6538C', color: '#FFFFFF' },
  sass: { label: 'CSS', background: '#C6538C', color: '#FFFFFF' },
  less: { label: 'CSS', background: '#2A4D80', color: '#FFFFFF' },
  html: { label: '<>', background: '#E34F26', color: '#FFFFFF' },
  htm: { label: '<>', background: '#E34F26', color: '#FFFFFF' },
  json: { label: '{}', background: '#CBCB41', color: '#1C1C1C' },
  jsonc: { label: '{}', background: '#CBCB41', color: '#1C1C1C' },
  yaml: { label: 'YML', background: '#CB171E', color: '#FFFFFF' },
  yml: { label: 'YML', background: '#CB171E', color: '#FFFFFF' },
  toml: { label: 'TML', background: '#9C4221', color: '#FFFFFF' },
  xml: { label: 'XML', background: '#F1662A', color: '#FFFFFF' },
  md: { label: 'MD', background: '#519ABA', color: '#FFFFFF' },
  mdx: { label: 'MD', background: '#519ABA', color: '#FFFFFF' },
  txt: { label: 'TXT', background: '#8B949E', color: '#FFFFFF' },
  log: { label: 'LOG', background: '#8B949E', color: '#FFFFFF' },
  ini: { label: 'INI', background: '#8B949E', color: '#FFFFFF' },
  cfg: { label: 'CFG', background: '#8B949E', color: '#FFFFFF' },
  conf: { label: 'CFG', background: '#8B949E', color: '#FFFFFF' },
  env: { label: 'ENV', background: '#D0A215', color: '#1C1C1C' },
  py: { label: 'PY', background: '#3572A5', color: '#FFFFFF' },
  rs: { label: 'RS', background: '#DEA584', color: '#1C1C1C' },
  go: { label: 'GO', background: '#00ADD8', color: '#FFFFFF' },
  java: { label: 'JV', background: '#B07219', color: '#FFFFFF' },
  kt: { label: 'KT', background: '#A97BFF', color: '#FFFFFF' },
  c: { label: 'C', background: '#5C6BC0', color: '#FFFFFF' },
  cc: { label: 'C+', background: '#5C6BC0', color: '#FFFFFF' },
  cpp: { label: 'C+', background: '#5C6BC0', color: '#FFFFFF' },
  cxx: { label: 'C+', background: '#5C6BC0', color: '#FFFFFF' },
  h: { label: 'H', background: '#5C6BC0', color: '#FFFFFF' },
  hpp: { label: 'H', background: '#5C6BC0', color: '#FFFFFF' },
  cs: { label: 'CS', background: '#178600', color: '#FFFFFF' },
  php: { label: 'PHP', background: '#777BB4', color: '#FFFFFF' },
  rb: { label: 'RB', background: '#CC342D', color: '#FFFFFF' },
  sh: { label: '>_', background: '#4EAA25', color: '#FFFFFF' },
  bash: { label: '>_', background: '#4EAA25', color: '#FFFFFF' },
  zsh: { label: '>_', background: '#4EAA25', color: '#FFFFFF' },
  ps1: { label: '>_', background: '#4EAA25', color: '#FFFFFF' },
  sql: { label: 'SQL', background: '#E38C00', color: '#FFFFFF' },
  pdf: { label: 'PDF', background: '#F5555D', color: '#FFFFFF' },
  xls: { label: 'XLS', background: '#217346', color: '#FFFFFF' },
  xlsx: { label: 'XLS', background: '#217346', color: '#FFFFFF' },
  ods: { label: 'XLS', background: '#217346', color: '#FFFFFF' },
  csv: { label: 'CSV', background: '#217346', color: '#FFFFFF' },
  doc: { label: 'DOC', background: '#2B579A', color: '#FFFFFF' },
  docx: { label: 'DOC', background: '#2B579A', color: '#FFFFFF' },
  odt: { label: 'DOC', background: '#2B579A', color: '#FFFFFF' },
  ppt: { label: 'PPT', background: '#D24726', color: '#FFFFFF' },
  pptx: { label: 'PPT', background: '#D24726', color: '#FFFFFF' },
  odp: { label: 'PPT', background: '#D24726', color: '#FFFFFF' },
  zip: { label: 'ZIP', background: '#FFA000', color: '#1C1C1C' },
  rar: { label: 'ZIP', background: '#FFA000', color: '#1C1C1C' },
  '7z': { label: 'ZIP', background: '#FFA000', color: '#1C1C1C' },
  tar: { label: 'ZIP', background: '#FFA000', color: '#1C1C1C' },
  gz: { label: 'ZIP', background: '#FFA000', color: '#1C1C1C' },
  bz2: { label: 'ZIP', background: '#FFA000', color: '#1C1C1C' },
  png: { label: 'IMG', background: '#A074C4', color: '#FFFFFF' },
  jpg: { label: 'IMG', background: '#A074C4', color: '#FFFFFF' },
  jpeg: { label: 'IMG', background: '#A074C4', color: '#FFFFFF' },
  gif: { label: 'IMG', background: '#A074C4', color: '#FFFFFF' },
  webp: { label: 'IMG', background: '#A074C4', color: '#FFFFFF' },
  bmp: { label: 'IMG', background: '#A074C4', color: '#FFFFFF' },
  svg: { label: 'IMG', background: '#A074C4', color: '#FFFFFF' },
  avif: { label: 'IMG', background: '#A074C4', color: '#FFFFFF' },
  mp3: { label: 'AUD', background: '#EE6E73', color: '#FFFFFF' },
  wav: { label: 'AUD', background: '#EE6E73', color: '#FFFFFF' },
  flac: { label: 'AUD', background: '#EE6E73', color: '#FFFFFF' },
  ogg: { label: 'AUD', background: '#EE6E73', color: '#FFFFFF' },
  mp4: { label: 'VID', background: '#7E57C2', color: '#FFFFFF' },
  webm: { label: 'VID', background: '#7E57C2', color: '#FFFFFF' },
  mov: { label: 'VID', background: '#7E57C2', color: '#FFFFFF' },
  avi: { label: 'VID', background: '#7E57C2', color: '#FFFFFF' },
}

const FALLBACK: BadgeStyle = { label: 'FILE', background: '#8B949E', color: '#FFFFFF' }
const FAILED_BACKGROUND = '#F5555D'

/** Extension of a display name or path, ignoring query strings and dotfiles. */
export function fileExtension(nameOrPath: string): string {
  const base = String(nameOrPath || '').split(/[?#]/, 1)[0]!.split(/[\\/]/).pop() || ''
  const dot = base.lastIndexOf('.')
  return dot > 0 && dot < base.length - 1 ? base.slice(dot + 1).toLowerCase() : ''
}

/**
 * Badge data for a file name or path. `failed` keeps the extension label but
 * turns the badge red, so a missing/failed file never looks like a valid one.
 */
export function fileTypeBadge(nameOrPath: string, failed = false): FileTypeBadgeData {
  const ext = fileExtension(nameOrPath)
  const style = STYLES[ext] || (ext ? { label: ext.slice(0, 3).toUpperCase(), background: FALLBACK.background, color: FALLBACK.color } : FALLBACK)
  return failed
    ? { label: style.label, background: FAILED_BACKGROUND, color: '#FFFFFF' }
    : { ...style }
}
