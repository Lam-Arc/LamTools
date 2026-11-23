import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// user:“避免零散 UI 样式”+(模型菜单承载玻璃，分组切换按钮留在实色操作层)。
const packageRoot = resolve(import.meta.dirname, '..')
const source = (relativePath: string): string => readFileSync(resolve(packageRoot, relativePath), 'utf8')

const menuSource = source('src/components/CoreModelThinkingMenu.vue')
const toggleSource = source('src/components/CoreModelCatalogViewToggle.vue')
const variablesCss = source('src/styles/variables.css')
const opticalGlassCss = source('src/styles/optical-glass.css')

describe('model thinking menu glass substrate', () => {
  it('keeps one shared filter token and mounts the primitive on it', () => {
    expect(variablesCss).toMatch(/--optical-glass-filter:\s*blur\(var\(--optical-glass-blur\)\)/)
    expect(opticalGlassCss.match(/var\(--optical-glass-filter\)/g)).toHaveLength(2)
  })

  it('uses shared glass on floating surfaces and solid fill for the toggle', () => {
    for (const name of ['glass', 'group-menu', 'hover-glass']) {
      expect(menuSource).toContain(`core-model-thinking-menu__${name} optical-glass optical-glass--low-trans`)
    }
    expect(menuSource).not.toContain('backdrop-filter:')
    expect(toggleSource).toContain('background: var(--theme-control-solid)')
    expect(toggleSource).not.toContain('backdrop-filter:')
  })
})
