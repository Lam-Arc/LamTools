/**
 * 预览的「分派表」——同一个文件到底由谁呈现。
 *
 * user:“预览的三态解析只有一份…任何「docx/xlsx/pptx 怎么显示」的判断都必须问它”+
 * (这里放唯一一份扩展名知识：浏览器能直接显示的、要本地渲染器排版的、能当文本读的、
 * 以及确实看不了的。灯箱与分屏都只读它，不再各自按扩展名分支)。
 *
 * 这一层是纯数据：不碰 DOM、不读字节，因此单测里零替身即可验证。
 * `resolve.ts` 在它之上补 URL 与 HTML 转换；`split/preview.ts` 只在它之上补
 * 「进编辑器还是进预览器」这一个判断。
 */

/** 浏览器自己能显示的媒体族；分屏据此选择 img / video / audio / PDF 画布。 */
export type PreviewMediaFamily = 'image' | 'video' | 'audio' | 'pdf'

/** 需要前端渲染器排版的文件：浏览器表面装不下版式。 */
export type PreviewLocalRenderer = 'docx' | 'xlsx' | 'pptx'

/** 一个文件在预览系统里的去向。 */
export type PreviewRoute =
  /**
   * 浏览器原生显示（iframe / img / video / audio / PDF 查看器）。
   * `raster` 表示浏览器自己解不了、要先由后端转成 PNG 的位图（TIF/TIFF）。
   */
  | { kind: 'native'; mime: string; family: PreviewMediaFamily; raster?: true }
  /** 纯文本 ↔ 只读文本面（项目内文本仍进编辑器）。 */
  | { kind: 'text' }
  /** Markdown：转换后排版显示。 */
  | { kind: 'markdown' }
  /** 由本地渲染器排版（灯箱没有这类渲染器，只有分屏有）。 */
  | { kind: 'local'; renderer: PreviewLocalRenderer }
  /** 明确看不了：给出原因，调用方提供「用默认应用打开」。 */
  | { kind: 'unsupported'; reason: string }

/** 文件名与扩展名：所有分派都只认这两个基础函数。 */
export function fileExtension(path: string): string {
  const name = path.replace(/\\/g, '/').split('/').pop() || ''
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : ''
}

export function baseName(path: string): string {
  return path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || path
}

/**
 * 浏览器原生就能显示的类型。
 *
 * user:“图片、音视频、PDF、纯文本都交给浏览器自己显示，不再为每种类型各写一套查看器”+
 */
export const NATIVE_MIME: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  bmp: 'image/bmp',
  ico: 'image/x-icon',
  svg: 'image/svg+xml',
  avif: 'image/avif',
  mp4: 'video/mp4',
  webm: 'video/webm',
  ogv: 'video/ogg',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  ogg: 'audio/ogg',
  oga: 'audio/ogg',
  m4a: 'audio/mp4',
  aac: 'audio/aac',
  flac: 'audio/flac',
  opus: 'audio/ogg',
  pdf: 'application/pdf',
}

/** 浏览器能当成纯文本显示的类型（读代码、看日志）。 */
export const TEXT_EXTENSIONS: ReadonlySet<string> = new Set([
  'txt', 'text', 'log', 'json', 'jsonc', 'json5', 'jsonl', 'yaml', 'yml', 'toml', 'ini', 'cfg',
  'conf', 'config', 'properties', 'env', 'csv', 'tsv', 'xml', 'html', 'htm', 'xhtml',
  'css', 'scss', 'sass', 'less', 'styl',
  'js', 'mjs', 'cjs', 'jsx', 'ts', 'mts', 'cts', 'tsx', 'vue', 'svelte', 'astro', 'py', 'pyw', 'pyi',
  'rb', 'php', 'pl', 'lua', 'r', 'go', 'rs', 'java', 'kt', 'kts', 'scala', 'groovy',
  'c', 'h', 'cc', 'cpp', 'cxx', 'hpp', 'hh', 'hxx', 'cs', 'fs', 'vb', 'swift', 'm', 'mm', 'dart',
  'sql', 'sh', 'bash', 'zsh', 'fish', 'ps1', 'psm1', 'bat', 'cmd', 'gradle', 'cmake', 'make',
  'proto', 'graphql', 'gql', 'diff', 'patch', 'tex', 'bib', 'srt', 'vtt', 'ass', 'ipynb',
  // Markdown 本身也按文本理解（分派时先命中 markdown 分支，见 resolvePreviewRoute）。
  'md', 'markdown',
  'mdx', 'rst', 'adoc', 'gitignore', 'gitattributes', 'editorconfig', 'npmrc', 'lock', 'map', 'plist',
])

/** 没有扩展名、但按文本处理的常见文件名。 */
export const TEXT_NAMES: ReadonlySet<string> = new Set([
  'dockerfile', 'makefile', 'cmakelists.txt', 'license', 'licence', 'readme', 'changelog',
  'authors', 'contributing', 'notice', '.gitignore', '.gitattributes', '.editorconfig',
  '.env', '.npmrc', '.prettierrc', '.eslintrc', '.babelrc', '.dockerignore',
])

/**
 * user:“除了Office类，别的都把它修好”+(TIF/TIFF 浏览器不认，但后端能把它转成 PNG：
 * 这里仍按「浏览器原生能看」分派，只是取内容要走 `preview-image` 那条转换通道)。
 */
export const RASTER_IMAGE_EXTENSIONS: ReadonlySet<string> = new Set(['tif', 'tiff'])

const MARKDOWN_EXTENSIONS: ReadonlySet<string> = new Set(['md', 'markdown'])

/** 需要本地渲染器排版的 Office 家族。 */
const LOCAL_RENDERERS: Record<string, PreviewLocalRenderer> = {
  docx: 'docx',
  xlsx: 'xlsx',
  xlsm: 'xlsx',
  pptx: 'pptx',
}

/**
 * 浏览器原生看不了、现在也没有本地渲染器的类型：说明原因，别假装能看。
 *
 * user:“不能看的，给的原因和动作与灯箱一致”+(原因写在唯一这处，分屏与灯箱显示同一句)。
 */
const UNSUPPORTED_REASONS: Record<string, string> = {
  mkv: '浏览器不能直接播放 MKV 视频；可以用默认应用打开',
  avi: '浏览器不能直接播放 AVI 视频；可以用默认应用打开',
  mov: '浏览器不能直接播放 MOV 视频；可以用默认应用打开',
  doc: '旧版 Word 文档不受支持；可以用默认应用打开',
  xls: '旧版 Excel 表格不受支持；可以用默认应用打开',
  ppt: '旧版演示文稿不受支持；可以用默认应用打开',
}

/** 本地渲染器在灯箱里的说法（灯箱没有这些渲染器，只说明去哪里看）。 */
export const LOCAL_RENDERER_REASONS: Record<PreviewLocalRenderer, string> = {
  docx: 'Word 文档的排版预览在分屏里查看；也可以用默认应用打开',
  xlsx: '表格的排版预览在分屏里查看；也可以用默认应用打开',
  pptx: '演示文稿的排版预览在分屏里查看；也可以用默认应用打开',
}

/** 这个路径是否按纯文本读（编辑器与只读文本面共用这一条判断）。 */
export function isTextPath(path: string): boolean {
  if (!path) return true
  const name = baseName(path).toLowerCase()
  return TEXT_EXTENSIONS.has(fileExtension(path)) || TEXT_NAMES.has(name) || name.startsWith('.')
}

/** 媒体族的 mime；不是浏览器原生类型时返回 null。 */
export function nativeMimeFor(path: string): string | null {
  return NATIVE_MIME[fileExtension(path)] || null
}

function familyOfMime(mime: string): PreviewMediaFamily {
  if (mime.startsWith('image/')) return 'image'
  if (mime.startsWith('video/')) return 'video'
  if (mime.startsWith('audio/')) return 'audio'
  return 'pdf'
}

/**
 * 唯一的分派入口：给一个路径，回它该由谁呈现。
 *
 * user:“不允许再出现「两套按扩展名分派」”+(灯箱与分屏都问这一个函数；
 * 任何新增类型只改这一张表)。
 */
export function resolvePreviewRoute(path: string): PreviewRoute {
  const extension = fileExtension(path)

  // Markdown 先于文本判定：它要排版，不是把源码当纯文本贴出来。
  if (MARKDOWN_EXTENSIONS.has(extension)) return { kind: 'markdown' }

  const local = LOCAL_RENDERERS[extension]
  if (local) return { kind: 'local', renderer: local }

  // 浏览器解不了的位图先由后端转 PNG，再当作图片给查看器。
  if (RASTER_IMAGE_EXTENSIONS.has(extension)) return { kind: 'native', mime: 'image/png', family: 'image', raster: true }

  const mime = NATIVE_MIME[extension]
  if (mime) return { kind: 'native', mime, family: familyOfMime(mime) }

  if (isTextPath(path)) return { kind: 'text' }

  const reason = UNSUPPORTED_REASONS[extension]
  if (reason) return { kind: 'unsupported', reason }

  return { kind: 'unsupported', reason: '浏览器无法直接显示这种文件类型；可以用默认应用打开' }
}
