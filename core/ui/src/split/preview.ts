// user:“分屏预览器不支持图片吗？改一下图片，视频 office，什么东西都尽可能支持一下”+
// (按文件类型把富媒体、文档与普通文本分开，决定分屏用预览器还是文本编辑器打开)。
export type SplitPreviewKind = 'image' | 'video' | 'audio' | 'pdf' | 'docx' | 'xlsx' | 'pptx' | 'markdown'

const PREVIEW_KINDS: Record<string, SplitPreviewKind> = {
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', bmp: 'image',
  ico: 'image', svg: 'image', avif: 'image', tif: 'image', tiff: 'image',
  mp4: 'video', webm: 'video', mov: 'video', m4v: 'video', ogv: 'video', mkv: 'video', avi: 'video',
  mp3: 'audio', wav: 'audio', ogg: 'audio', oga: 'audio', m4a: 'audio', flac: 'audio', aac: 'audio', opus: 'audio',
  pdf: 'pdf',
  docx: 'docx',
  xlsx: 'xlsx', xlsm: 'xlsx',
  pptx: 'pptx',
  md: 'markdown', markdown: 'markdown',
}

const TEXT_EXTENSIONS = new Set([
  'txt', 'text', 'md', 'markdown', 'mdx', 'rst', 'adoc', 'log', 'json', 'jsonc', 'json5', 'jsonl',
  'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'config', 'properties', 'env', 'csv', 'tsv',
  'xml', 'html', 'htm', 'xhtml', 'css', 'scss', 'sass', 'less', 'styl',
  'js', 'mjs', 'cjs', 'jsx', 'ts', 'mts', 'cts', 'tsx', 'vue', 'svelte', 'astro',
  'py', 'pyw', 'pyi', 'rb', 'php', 'pl', 'lua', 'r', 'go', 'rs', 'java', 'kt', 'kts', 'scala', 'groovy',
  'c', 'h', 'cc', 'cpp', 'cxx', 'hpp', 'hh', 'hxx', 'cs', 'fs', 'vb', 'swift', 'm', 'mm', 'dart',
  'sql', 'sh', 'bash', 'zsh', 'fish', 'ps1', 'psm1', 'bat', 'cmd', 'gradle', 'cmake', 'make',
  'proto', 'graphql', 'gql', 'diff', 'patch', 'tex', 'bib', 'srt', 'vtt', 'ass', 'gitignore', 'gitattributes',
  'editorconfig', 'npmrc', 'lock', 'map', 'plist', 'ipynb',
])

const TEXT_NAMES = new Set([
  'dockerfile', 'makefile', 'cmakelists.txt', 'license', 'licence', 'readme', 'changelog',
  'authors', 'contributing', 'notice', '.gitignore', '.gitattributes', '.editorconfig',
  '.env', '.npmrc', '.prettierrc', '.eslintrc', '.babelrc', '.dockerignore',
])

export function fileExtension(path: string): string {
  const name = path.replace(/\\/g, '/').split('/').pop() || ''
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : ''
}

export function baseName(path: string): string {
  return path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || path
}

/** 可预览类型；普通文本与未知文件返回 null。 */
export function previewKindFor(path: string): SplitPreviewKind | null {
  return PREVIEW_KINDS[fileExtension(path)] || null
}

export function isTextPath(path: string): boolean {
  if (!path) return true
  const name = baseName(path).toLowerCase()
  return TEXT_EXTENSIONS.has(fileExtension(path)) || TEXT_NAMES.has(name) || name.startsWith('.')
}

/**
 * user:“默认打开也跟文本文件一样 用分屏预览打开”+
 * (文本继续用编辑器，图片/音视频/PDF/Office 以及无法判断类型的文件都进预览器)。
 */
export function splitContentFor(path: string): 'preview' | 'editor' {
  return !path || (isTextPath(path) && !previewKindFor(path)) ? 'editor' : 'preview'
}
