// user:“全面盘点：梳理所有可见的组件、样式、布局、动效及交互”+(生成可复查的源码索引，候选项仍需人工确认)
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, extname, join, relative, resolve, posix } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
// user:“不用管 website ，只用管 Sunday 这一个应用”+(索引范围限定为桌面应用与随附插件界面)
const roots = ['core/ui/src', 'core/desktop/src', 'core/src/lamtools_core/plugins/bundled']
const patterns = [
  ['button', /<button\b|role\s*=\s*["']button["']/i],
  ['checkbox', /type\s*=\s*["']checkbox["']/i],
  ['switch', /role\s*=\s*["']switch["']|<SundaySwitch\b/i],
  ['range', /type\s*=\s*["']range["']|<SundayRange\b/i],
  ['select', /<select\b|<UiSelect\b/i],
  ['dialog', /role\s*=\s*["']dialog["']|<dialog\b/i],
  ['event', /@(?:click|change|input|key\w*|pointer\w*|submit)\b|addEventListener\s*\(/i],
  ['grid', /display\s*:\s*(?:inline-)?grid/i],
  ['flex', /display\s*:\s*(?:inline-)?flex/i],
  ['animation', /animation(?:-name)?\s*:|<Transition(?:Group)?\b|gsap\.(?:to|from|timeline)|@keyframes\b/i],
  ['reduced-motion', /prefers-reduced-motion/i],
  ['theme', /--theme-[\w-]+/i],
  ['tokens', /var\(--(?:space|radius|dur|ease|shadow|z)-?[\w-]*/i],
]
export function analyzeSource(path, source) {
  // user:“全面盘点：梳理所有可见的组件、样式、布局、动效及交互”+(列出未接入共享控件的原生写法，供人工确认用途)。
  const inputs = [...source.matchAll(/<input\b[^>]*>/gi)].map(match => match[0])
  const nativeCandidates = {
    select: [...source.matchAll(/<select\b/gi)].length,
    checkbox: inputs.filter(tag => /type\s*=\s*["']checkbox["']/i.test(tag) && !/sunday-checkbox|sunday-switch__input/.test(tag)).length,
    range: inputs.filter(tag => /type\s*=\s*["']range["']/i.test(tag) && !/sunday-range__input/.test(tag)).length,
  }
  return { path: path.replaceAll('\\', '/'), signals: patterns.filter(([, regex]) => regex.test(source)).map(([name]) => name), nativeCandidates }
}
// user:“建立组件目录、使用说明与复用规范，让后续开发及 Agent 能快速检索”+(记录静态导入位置，供迁移时核对调用方)
export function componentImports(path, source) {
  const matches = source.matchAll(/(?:\bfrom\s*|\bimport\s*\(\s*)["']([^"']+\.vue)["']/g)
  const resolved = []
  for (const match of matches) {
    const target = match[1]
    // user:“建立组件目录、使用说明与复用规范，让后续开发及 Agent 能快速检索”+(桌面入口与主界面的 @ 均指向 core/ui/src)。
    if (target.startsWith('@/') && (path.startsWith('core/ui/src/') || path.startsWith('core/desktop/src/'))) resolved.push(posix.normalize(`core/ui/src/${target.slice(2)}`))
    else if (target.startsWith('.')) resolved.push(posix.normalize(posix.join(posix.dirname(path), target)))
  }
  return [...new Set(resolved)]
}
export function renderUsage(files) {
  const users = new Map()
  for (const file of files) for (const target of file.imports) {
    if (!users.has(target)) users.set(target, [])
    users.get(target).push(file.path)
  }
  const lines = ['# Vue 组件静态调用索引', '', '由 `node scripts/ui-inventory.mjs` 生成。仅覆盖源码中的显式 Vue 文件导入，动态注册、别名和运行时插件等可能遗漏；迁移前仍需搜索和检查实际行为。', '']
  for (const [component, callers] of [...users.entries()].sort(([a], [b]) => a.localeCompare(b, 'en'))) {
    // user:“全面盘点”+(区分展厅及实验页调用，避免把预览当成生产页面引用)。
    lines.push(`## ${component}`, '', ...callers.sort().map(path => `- [${path}](../${path})${(/\/(?:design-system|demo)\//.test(path) || /^core\/desktop\/src\/.*(?:lab|preview)\.ts$/i.test(path)) ? '（预览入口）' : ''}`), '')
  }
  return lines.join('\n')
}
// user:“建立组件目录、使用说明与复用规范，让后续开发及 Agent 能快速检索”+(组件目录保存静态调用方和源码线索，并区分预览入口)。
export function renderComponentIndex(files) {
  const callers = new Map()
  for (const file of files) for (const target of file.imports || []) {
    if (!callers.has(target)) callers.set(target, [])
    callers.get(target).push(file.path)
  }
  const isPreview = path => /\/(?:design-system|demo)\//.test(path) || /^core\/desktop\/src\/.*(?:lab|preview)\.ts$/i.test(path)
  return files.filter(file => file.path.endsWith('.vue')).map(file => {
    const references = [...new Set(callers.get(file.path) || [])].sort()
    return { path: file.path, name: posix.basename(file.path, '.vue'), signals: file.signals, callers: references.filter(path => !isPreview(path)), previewCallers: references.filter(isPreview) }
  })
}
export function renderInventory(files) {
  const counts = Object.fromEntries(patterns.map(([name]) => [name, files.filter(file => file.signals.includes(name)).length]))
  return [
    '# 前端源码盘点索引', '',
    '由 `node scripts/ui-inventory.mjs` 从源码生成。范围包括 Sunday 桌面入口、界面及随附插件界面；不扫描移动端、官网、独立插件和归档。文件存在或匹配某种写法不等于该界面一定可达、组件可复用或存在缺陷。需要结合调用关系、实际状态和主题逐项核对。', '',
    `共 ${files.length} 个文件。标记是粗略线索，不是问题数量：`, '',
    ...Object.entries(counts).map(([name, count]) => `- ${name}: ${count}`), '',
    '## 原生控件候选', '',
    '仅按源码标记估算，可能包含实验页、专用控件或动态属性；不是缺陷清单。', '',
    ...files.filter(file => Object.values(file.nativeCandidates || {}).some(Boolean)).map(file => `- [${file.path}](../${file.path})：${Object.entries(file.nativeCandidates).filter(([, count]) => count).map(([name, count]) => `${name}: ${count}`).join('、')}`), '',
    '## 文件与线索', '', '| 源文件 | 线索 |', '| --- | --- |',
    ...files.map(file => `| [${file.path}](../${file.path}) | ${file.signals.join('、') || '—'} |`), '',
  ].join('\n')
}
async function walk(path) {
  const result = []
  for (const entry of await readdir(path, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist') continue
    const full = join(path, entry.name)
    if (entry.isDirectory()) result.push(...await walk(full))
    // user:“全面盘点：梳理所有可见的组件、样式、布局、动效及交互”+(类型声明不是界面源码，不混入盘点结果)。
    else if (!entry.name.endsWith('.d.ts') && ['.vue', '.css', '.html', '.ts', '.js', '.mjs'].includes(extname(entry.name))) result.push(full)
  }
  return result
}
// user:“不用管 website ，只用管 Sunday 这一个应用”+(仅索引应用桌面入口与随附插件界面)
export async function collectUiPaths() {
  const all = (await Promise.all(roots.map(path => walk(join(root, path))))).flat()
    .filter(path => !path.includes(`${join('plugins', 'bundled')}\\`) && !path.includes('/plugins/bundled/') || /[\\/]ui[\\/]/.test(path))
  for (const area of ['core/ui', 'core/desktop']) {
    for (const entry of await readdir(join(root, area), { withFileTypes: true })) {
      if (entry.isFile() && entry.name.endsWith('.html') && !/android|mobile/i.test(entry.name)) all.push(join(root, area, entry.name))
    }
  }
  // user:“不用管 website ，只用管 Sunday 这一个应用”+(排除归档代码与移动端入口，避免将历史页面误作当前桌面组件)。
  return [...new Set(all.map(path => relative(root, path).replaceAll('\\', '/')))].filter(path => !/\/archived\//i.test(path) && !/\/(?:MobileTopBar\.vue|main-android\.ts)$/i.test(path))
}
async function main() {
  const all = await collectUiPaths()
  const files = await Promise.all(all.map(async name => {
    const source = await readFile(join(root, name), 'utf8')
    return { ...analyzeSource(name, source), imports: componentImports(name, source) }
  }))
  files.sort((a, b) => a.path.localeCompare(b.path, 'en'))
  await writeFile(join(root, 'agent_docs/ui_inventory.md'), renderInventory(files), 'utf8')
  await writeFile(join(root, 'agent_docs/ui_component_usage.md'), renderUsage(files), 'utf8')
  // user:“建立组件目录……让后续开发及 Agent 能快速检索”+(展厅索引随同一盘点脚本刷新，不把未验证页面冒充为可操作样例)
  const components = renderComponentIndex(files)
  await writeFile(join(root, 'core/ui/src/design-system/component-inventory.json'), `${JSON.stringify(components, null, 2)}\n`, 'utf8')
  console.log(`Indexed ${files.length} UI source files`)
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await main()
