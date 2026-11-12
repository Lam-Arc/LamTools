/**
 * One shared file-type glyph for composer tokens, message references and the
 * attachment tray.
 *
 * user:“我需要你去重做重新设计各附件的图标，最好一眼就能看出来这是个什么类型文件”+
 * (按扩展名归到固定类别，再用类别图标 + 类别色区分；图形保持 24×24 线稿风格，
 * 小尺寸下仍能看出图片/视频/音频/PDF/Word/表格/演示/压缩包/代码等差异)。
 */

export type FileCategory =
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'word'
  | 'sheet'
  | 'presentation'
  | 'archive'
  | 'code'
  | 'json'
  | 'markdown'
  | 'html'
  | 'text'
  | 'file'

type IconNode = [tag: string, attrs: Record<string, string | number>]

const GLYPHS: Record<FileCategory, IconNode[]> = {
  image: [
    ['rect', { x: 3, y: 4, width: 18, height: 16, rx: 3 }],
    ['circle', { cx: 8.5, cy: 9.5, r: 1.6 }],
    ['path', { d: 'M21 15.5 16 11l-8.5 9' }],
  ],
  video: [
    ['rect', { x: 3, y: 5, width: 13, height: 14, rx: 3 }],
    ['path', { d: 'M16 9.5 21 6.5v11l-5-3z' }],
  ],
  audio: [
    ['path', { d: 'M9 17V6l10-2v11' }],
    ['circle', { cx: 6, cy: 18, r: 3 }],
    ['circle', { cx: 16, cy: 16, r: 3 }],
  ],
  pdf: [
    ['path', { d: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z' }],
    ['path', { d: 'M14 3v5h5' }],
    ['path', { d: 'M9.5 17v-5h1.8a1.6 1.6 0 0 1 0 3.2H9.5' }],
  ],
  word: [
    ['path', { d: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z' }],
    ['path', { d: 'M14 3v5h5' }],
    ['path', { d: 'M8 13l1.5 4L11 14l1.5 3L14 13' }],
  ],
  sheet: [
    ['rect', { x: 4, y: 4, width: 16, height: 16, rx: 3 }],
    ['path', { d: 'M4 10h16M4 15h16M10 4v16M15 4v16' }],
  ],
  presentation: [
    ['rect', { x: 3, y: 4, width: 18, height: 12, rx: 2 }],
    ['path', { d: 'M12 16v4M8 21h8' }],
    ['path', { d: 'M7 8h10M7 11h6' }],
  ],
  archive: [
    ['rect', { x: 3, y: 4, width: 18, height: 5, rx: 2 }],
    ['path', { d: 'M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9' }],
    ['path', { d: 'M12 12v3M10 15h4' }],
  ],
  code: [
    ['path', { d: 'M8 8l-4 4 4 4M16 8l4 4-4 4' }],
    ['path', { d: 'M13 5l-2 14' }],
  ],
  json: [
    ['path', { d: 'M9 4c-2 0-3 1-3 3v2c0 2-1 3-2 3 1 0 2 1 2 3v2c0 2 1 3 3 3' }],
    ['path', { d: 'M15 4c2 0 3 1 3 3v2c0 2 1 3 2 3-1 0-2 1-2 3v2c0 2-1 3-3 3' }],
  ],
  markdown: [
    ['path', { d: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z' }],
    ['path', { d: 'M14 3v5h5' }],
    ['path', { d: 'M8 17v-6l2 2 2-2v6' }],
  ],
  html: [
    ['circle', { cx: 12, cy: 12, r: 9 }],
    ['path', { d: 'M3 12h18M12 3c2.8 2.4 4.2 5.4 4.2 9S14.8 18.6 12 21c-2.8-2.4-4.2-5.4-4.2-9S9.2 5.4 12 3z' }],
  ],
  text: [
    ['path', { d: 'M5 7h14M5 12h10M5 17h14' }],
  ],
  file: [
    ['path', { d: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z' }],
    ['path', { d: 'M14 3v5h5' }],
  ],
}

const CATEGORY_BY_EXTENSION: Record<string, FileCategory> = {
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', bmp: 'image',
  ico: 'image', svg: 'image', avif: 'image', tif: 'image', tiff: 'image', heic: 'image', heif: 'image',
  mp4: 'video', webm: 'video', mov: 'video', m4v: 'video', ogv: 'video', mkv: 'video', avi: 'video',
  mp3: 'audio', wav: 'audio', ogg: 'audio', oga: 'audio', m4a: 'audio', flac: 'audio', aac: 'audio',
  opus: 'audio', wma: 'audio',
  pdf: 'pdf',
  doc: 'word', docx: 'word', odt: 'word', rtf: 'word', pages: 'word',
  xls: 'sheet', xlsx: 'sheet', xlsm: 'sheet', ods: 'sheet', csv: 'sheet', tsv: 'sheet', numbers: 'sheet',
  ppt: 'presentation', pptx: 'presentation', odp: 'presentation', key: 'presentation',
  zip: 'archive', rar: 'archive', '7z': 'archive', tar: 'archive', gz: 'archive', bz2: 'archive',
  xz: 'archive', tgz: 'archive',
  ts: 'code', tsx: 'code', mts: 'code', cts: 'code', js: 'code', jsx: 'code', mjs: 'code', cjs: 'code',
  vue: 'code', svelte: 'code', py: 'code', pyw: 'code', pyi: 'code', rb: 'code', php: 'code',
  go: 'code', rs: 'code', java: 'code', kt: 'code', kts: 'code', scala: 'code', swift: 'code',
  c: 'code', h: 'code', cc: 'code', cpp: 'code', cxx: 'code', hpp: 'code', cs: 'code',
  sh: 'code', bash: 'code', zsh: 'code', fish: 'code', ps1: 'code', bat: 'code', cmd: 'code',
  sql: 'code', lua: 'code', r: 'code', dart: 'code', ex: 'code', exs: 'code', erl: 'code',
  json: 'json', jsonc: 'json', json5: 'json', jsonl: 'json',
  yaml: 'json', yml: 'json', toml: 'json', xml: 'json', ini: 'json', cfg: 'json', conf: 'json',
  env: 'json', lock: 'json',
  md: 'markdown', mdx: 'markdown', markdown: 'markdown',
  html: 'html', htm: 'html', xhtml: 'html',
  txt: 'text', text: 'text', log: 'text', rst: 'text', adoc: 'text', tex: 'text',
}

/** Category for a file name or path; unknown extensions fall back to a plain file. */
export function fileCategory(nameOrPath: string): FileCategory {
  const base = String(nameOrPath || '').split(/[?#]/, 1)[0]!.split(/[\\/]/).pop() || ''
  const dot = base.lastIndexOf('.')
  const extension = dot > 0 && dot < base.length - 1 ? base.slice(dot + 1).toLowerCase() : ''
  return CATEGORY_BY_EXTENSION[extension] || 'file'
}

/** Inline SVG markup; stroke uses currentColor so category colors apply. */
export function fileTypeIconMarkup(nameOrPath: string, size = 16, strokeWidth = 1.9): string {
  const glyph = GLYPHS[fileCategory(nameOrPath)] || GLYPHS.file
  const body = glyph.map(([tag, attrs]) => {
    const pairs = Object.entries(attrs).map(([key, value]) => `${key}="${value}"`).join(' ')
    return `<${tag} ${pairs}/>`
  }).join('')
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" `
    + `stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`
}
