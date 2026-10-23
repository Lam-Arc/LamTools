import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { resolve, dirname, basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

// user:“先把文本内容给做好” (只验收词条覆盖、有效链接与可核查来源，不涉及页面设计。)
const root = fileURLToPath(new URL('..', import.meta.url))
const articles = join(root, 'articles')
const files = readdirSync(articles).filter(file => file.endsWith('.md'))
const index = readFileSync(join(root, 'README.md'), 'utf8')
const required = ['welcome', 'quick-start', 'projects', 'sessions', 'models', 'attachments', 'approvals', 'skills', 'plugins', 'mcp', 'sub-agents', 'memory', 'compaction', 'arrange', 'workflow', 'study', 'library', 'web-search', 'imagegen', 'desktop-pet', 'updates', 'privacy', 'troubleshooting', 'glossary', 'queued-messages', 'runtime-status', 'artifacts']
const errors = []
function check(condition, message) { if (!condition) errors.push(message) }
check(files.length >= 55, `功能词条不足：${files.length}，目标至少 55`)
for (const id of required) check(files.includes(`${id}.md`), `缺少词条：${id}`)
for (const filename of ['README.md', ...files.map(file => `articles/${file}`)]) {
  const path = join(root, filename)
  const text = readFileSync(path, 'utf8')
  check(text.startsWith('# '), `${filename} 缺少主标题`)
  if (filename !== 'README.md') {
    check(text.length >= 550, `${filename} 需要充实说明`)
    check((text.match(/^## /gm) || []).length >= 3, `${filename} 缺少完整的使用说明`)
    check(text.includes('来源'), `${filename} 缺少来源`)
    check(index.includes(`articles/${basename(filename)}`), `总目录未收录 ${filename}`)
  }
  for (const match of text.matchAll(/\[[^\]]*\]\(([^)]+)\)/g)) {
    const target = match[1].replace(/^<|>$/g, '').split('#')[0]
    if (!target || /^[a-z]+:/i.test(target)) continue
    check(existsSync(resolve(dirname(path), decodeURIComponent(target))), `${filename} 链接不存在：${target}`)
  }
}
assert.equal(errors.length, 0, errors.join('\n'))
console.log(`已验证 ${files.length} 个词条：覆盖清单、总目录收录、内容结构与本地链接全部通过。`)
