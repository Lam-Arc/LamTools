import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import * as lucideIcons from 'lucide-vue-next'

/**
 * 模板里写到的 lucide 图标必须真的 import 进来。
 *
 * 漏一个，Vue 在解析组件时就解析不到，于是每次渲染该组件都发一条
 * "Failed to resolve component" 警告（警告不去重），图标本身也渲染不出来。
 * 更糟的是这条警告把组件 props 当对象参数一起带出去：根组件的 props 里是
 * 整份运行时配置，宿主把它序列化进日志，一条警告就是几百 KB，流式期间每帧一条。
 */
const SRC_ROOT = resolve(import.meta.dirname, '../src')
const LUCIDE_EXPORTS = new Set(Object.keys(lucideIcons))

function vueFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) vueFiles(path, out)
    else if (entry.endsWith('.vue')) out.push(path)
  }
  return out
}

/** 该文件从 lucide-vue-next 具名导入的名字（含 as 别名后的名字）。 */
function lucideImportNames(source: string): Set<string> {
  const names = new Set<string>()
  for (const match of source.matchAll(/import\s*\{([^{}]*)\}\s*from\s*['"]lucide-vue-next['"]/g)) {
    for (const raw of match[1].split(',')) {
      const name = raw.trim().split(/\s+as\s+/).pop()?.trim()
      if (name) names.add(name)
    }
  }
  return names
}

/** 模板区域里用到的 PascalCase 标签名；script/style/注释先剔除。 */
function templateTags(source: string): Set<string> {
  const markup = source
    .replace(/<script[\s\S]*?<\/script>/g, '')
    .replace(/<style[\s\S]*?<\/style>/g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
  const tags = new Set<string>()
  for (const match of markup.matchAll(/<([A-Z][A-Za-z0-9]*)/g)) tags.add(match[1])
  return tags
}

function relative(file: string): string {
  return file.slice(SRC_ROOT.length + 1).split('\\').join('/')
}

describe('lucide icon imports', () => {
  it('enumerates the icon namespace (guards the check below)', () => {
    // 若命名空间枚举失效，下面的比对就会永远为空而静默失效。
    expect(LUCIDE_EXPORTS.size).toBeGreaterThan(1000)
  })

  // 扫全仓 SFC + 枚举 lucide 命名空间；整仓并行跑时 5s 默认超时会被挤爆。
  it('imports every lucide icon referenced from a template', () => {
    const missing: string[] = []
    for (const file of vueFiles(SRC_ROOT)) {
      const source = readFileSync(file, 'utf8')
      const imported = lucideImportNames(source)
      for (const tag of templateTags(source)) {
        if (!LUCIDE_EXPORTS.has(tag) || imported.has(tag)) continue
        missing.push(`${relative(file)}: ${tag}`)
      }
    }
    expect(missing).toEqual([])
  }, 30_000)

  it('keeps the mobile footer library entry resolvable', () => {
    const source = readFileSync(resolve(SRC_ROOT, 'app/LamToolsApp.vue'), 'utf8')
    expect(source).toContain('data-mobile-footer-library')
    expect(lucideImportNames(source).has('Library')).toBe(true)
    // 图标本身确实存在于依赖里（不是拼错的名字）。
    expect(lucideIcons.Library).toBeTruthy()
  })
})
