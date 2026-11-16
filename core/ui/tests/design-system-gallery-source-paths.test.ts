// @vitest-environment node
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

// user:“源码定位”“建立组件目录、使用说明与复用规范”+(展厅登记的主源码与组合组件路径必须真实存在)。
describe('gallery source paths', () => {
  it('resolves every declared preview path in the Sunday workspace', () => {
    const uiRoot = resolve(import.meta.dirname, '..')
    const script = parse(readFileSync(resolve(uiRoot, 'src/design-system/Gallery.vue'), 'utf8')).descriptor.scriptSetup!.content
    const source = ts.createSourceFile('gallery.ts', script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    const declarations = source.statements.filter(ts.isVariableStatement).flatMap(statement => [...statement.declarationList.declarations])
    const entries = declarations.find(node => ts.isIdentifier(node.name) && node.name.text === 'entries')?.initializer
    expect(entries && ts.isArrayLiteralExpression(entries)).toBe(true)
    const missing: string[] = []
    for (const entry of (entries as ts.ArrayLiteralExpression).elements) {
      if (!ts.isObjectLiteralExpression(entry)) continue
      const property = (name: string) => entry.properties.find(p => ts.isPropertyAssignment(p) && p.name.getText(source) === name) as ts.PropertyAssignment | undefined
      const name = property('name')?.initializer
      expect(name && ts.isStringLiteral(name)).toBe(true)
      const path = property('sourcePath')?.initializer
      const primary = path && ts.isStringLiteral(path) ? resolve(uiRoot, path.text) : resolve(uiRoot, `src/components/${(name as ts.StringLiteral).text}.vue`)
      if (!existsSync(primary)) missing.push(primary)
      const additional = property('alsoPreviews')?.initializer
      if (additional && ts.isArrayLiteralExpression(additional)) for (const item of additional.elements) {
        if (ts.isStringLiteral(item)) { const candidate = resolve(uiRoot, '../..', item.text); if (!existsSync(candidate)) missing.push(candidate) }
      }
    }
    expect(missing).toEqual([])
  })
})
