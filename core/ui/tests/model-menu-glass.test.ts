import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 模型/思考菜单的玻璃底板。
 *
 * user:“为什么前面那个面板没有模糊”“修”+(菜单卡片、分组下拉和组/供应商切换胶囊都要跟其它
 * 浮层一样带毛玻璃：只写半透明底色会把背后的文字原样透出来。)
 *
 * 这三处底板是手写背景（卡片底板还挂在 ::before 上做划开动画），没法直接套 .optical-glass
 * 类，所以统一复用 shared 滤镜令牌，避免各自复制一串 blur/saturate 表达式。
 */

const packageRoot = resolve(import.meta.dirname, '..')
const source = (relativePath: string): string => readFileSync(resolve(packageRoot, relativePath), 'utf8')

const menuSource = source('src/components/CoreModelThinkingMenu.vue')
const toggleSource = source('src/components/CoreModelCatalogViewToggle.vue')
const variablesCss = source('src/styles/variables.css')
const opticalGlassCss = source('src/styles/optical-glass.css')

function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return css.match(new RegExp(`${escaped}\\s*\\{[\\s\\S]*?\\n\\}`))?.[0] ?? ''
}

describe('model thinking menu glass substrate', () => {
  it('keeps one shared filter token and mounts the primitive on it', () => {
    expect(variablesCss).toMatch(/--optical-glass-filter:\s*blur\(var\(--optical-glass-blur\)\)/)
    expect(opticalGlassCss.match(/var\(--optical-glass-filter\)/g)).toHaveLength(2)
  })

  it('frosts the card base, the group menu and the catalog view toggle', () => {
    const surfaces = [
      rule(menuSource, '.core-model-thinking-menu__card::before'),
      rule(menuSource, '.core-model-thinking-menu__group-menu'),
      rule(toggleSource, '.model-catalog-view-toggle'),
    ]
    for (const surface of surfaces) {
      expect(surface).toContain('backdrop-filter: var(--optical-glass-filter)')
      expect(surface).toContain('-webkit-backdrop-filter: var(--optical-glass-filter)')
    }
  })
})
