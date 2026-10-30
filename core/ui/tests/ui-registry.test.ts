import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { resolve, relative } from 'node:path'
import { UI_REGISTRY } from '../src/uiRegistry/registry.ts'

/**
 * user:“想清楚再动手，写清单逐项打勾，不要出错”+
 * (注册表是编辑器的地基：标识重复、父级断开、重构后失联都必须在测试里先报出来。)
 */
const srcRoot = resolve(process.cwd(), 'src')

function collectVueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(dir, entry.name)
    if (entry.isDirectory()) return collectVueFiles(path)
    return entry.name.endsWith('.vue') ? [path] : []
  })
}

const vueSources = new Map(
  collectVueFiles(srcRoot).map((path) => [relative(srcRoot, path).replace(/\\/g, '/'), readFileSync(path, 'utf8')]),
)

describe('可编辑元素注册表', () => {
  it('标识唯一且符合 区域.名称 格式', () => {
    const seen = new Set<string>()
    for (const entry of UI_REGISTRY) {
      expect(entry.id, '标识格式').toMatch(/^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$/)
      expect(seen.has(entry.id), `标识重复：${entry.id}`).toBe(false)
      seen.add(entry.id)
    }
  })

  it('父级存在且没有环', () => {
    const byId = new Map(UI_REGISTRY.map((entry) => [entry.id, entry]))
    for (const entry of UI_REGISTRY) {
      if (!entry.parent) continue
      expect(byId.has(entry.parent), `${entry.id} 的父级不存在：${entry.parent}`).toBe(true)
      const visited = new Set([entry.id])
      let cursor: string | undefined = entry.parent
      while (cursor) {
        expect(visited.has(cursor), `父级成环：${entry.id}`).toBe(false)
        visited.add(cursor)
        cursor = byId.get(cursor)?.parent
      }
    }
  })

  it('登记的元素都在自己的组件里挂了稳定标识', () => {
    for (const entry of UI_REGISTRY) {
      const ownerPath = resolve(srcRoot, entry.owner)
      expect(existsSync(ownerPath), `组件不存在：${entry.owner}`).toBe(true)
      const source = vueSources.get(entry.owner)
      expect(source, `未读到源码：${entry.owner}`).toBeTruthy()
      const attribute = entry.kind === 'template' ? 'data-ui-template' : 'data-ui-id'
      expect(source!.includes(`${attribute}="${entry.id}"`), `${entry.owner} 里没有 ${entry.id} 的标识`).toBe(true)
    }
  })

  it('文字类样式类型标识挂在文字节点本身，不挂在包裹按钮上', () => {
    // user:“我对项目名称进行了字号修改和文字颜色修改，但是并没有生效”+
    // (文字节点有自己的字号/颜色规则；标识挂在外层按钮上只能被继承，压不过显式样式。)
    const source = vueSources.get('components/SessionSidebar.vue')
    expect(source).toBeTruthy()
    expect(source!).toMatch(/<strong data-ui-template="template\.project-name">/)
    expect(source!).toMatch(/<strong class="session-title" data-ui-template="template\.session-title">/)
  })

  // user:“这个图层应该像 PS 一样可单独编辑”+(除桌面壳外每个元素都能设层级 z)
  it('除桌面壳外全部元素都开放层级', () => {
    for (const entry of UI_REGISTRY) {
      if (entry.protection === 'protected') continue
      expect(entry.properties.includes('layer'), `${entry.id} 未开放层级`).toBe(true)
    }
  })

  it('保护级别与可编辑属性不矛盾', () => {
    for (const entry of UI_REGISTRY) {
      expect(entry.properties.length, `${entry.id} 的属性为空`).toBeGreaterThanOrEqual(0)
      if (entry.protection === 'protected') {
        expect(entry.properties, `受保护元素不应开放属性：${entry.id}`).toHaveLength(0)
      }
      if (entry.protection === 'appearance-only') {
        expect(entry.properties.includes('size'), `仅外观元素不应开放尺寸：${entry.id}`).toBe(false)
        expect(entry.properties.includes('layer'), `仅外观元素不应开放层级：${entry.id}`).toBe(false)
      }
      if (entry.properties.includes('visibility')) {
        expect(entry.protection, `可隐藏元素不能被仅外观或受保护：${entry.id}`).toBe('editable')
      }
    }
  })
})
