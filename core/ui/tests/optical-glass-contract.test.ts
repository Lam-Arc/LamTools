import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const packageRoot = resolve(import.meta.dirname, '..')
const source = (relativePath: string): string => readFileSync(resolve(packageRoot, relativePath), 'utf8')

const opticalGlassCss = source('src/styles/optical-glass.css')
const variablesCss = source('src/styles/variables.css')
const layoutCss = source('src/styles/layout.css')
const shellCss = source('src/styles/workspace-shell.css')
const appSource = source('src/app/LamToolsApp.vue')
const contextSource = source('src/components/context-menu/ContextMenuPanel.vue')
const mobileSource = source('src/components/MobileTopBar.vue')
const selectionSource = source('src/study/SelectionAssistant.vue')
const catalogSource = readFileSync(resolve(packageRoot, '../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeCatalog.vue'), 'utf8')
const runtimeDockSource = readFileSync(resolve(packageRoot, '../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeRuntimeDock.vue'), 'utf8')

describe('shared optical glass contract', () => {
  it('keeps the substrate high-transmission and physically restrained', () => {
    expect(variablesCss).toMatch(/--optical-glass-blur:\s*var\(--space-2\)/)
    expect(variablesCss).toMatch(/--optical-glass-saturation:\s*1\.14/)
    expect(variablesCss).toMatch(/--optical-glass-brightness:\s*1\.02/)
    expect(variablesCss).toMatch(/--optical-glass-tint:\s*16%/)
    expect(variablesCss).toContain('--optical-glass-highlight-color: rgb(255 255 255)')
    expect(variablesCss).toMatch(/--optical-glass-reflection:\s*10%/)
    expect(variablesCss).toContain('--optical-glass-edge-color: rgb(115 132 121)')
    expect(variablesCss).toContain('--optical-glass-inset-top: 56%')
    expect(variablesCss).toContain('--optical-glass-shadow: 0 7px 14px')
    expect(opticalGlassCss).toContain('overflow: hidden;')
    expect(opticalGlassCss).toContain('-webkit-backdrop-filter:')
    expect(opticalGlassCss).toContain('backdrop-filter:')
    expect(opticalGlassCss).toMatch(/@supports not \(\(backdrop-filter: blur\(1px\)\) or \(-webkit-backdrop-filter: blur\(1px\)\)\)/)
    expect(opticalGlassCss).toMatch(/border: 1px solid color-mix\(in srgb, var\(--optical-glass-edge-color\)/)
    expect(opticalGlassCss).toMatch(/\.optical-glass::before\s*\{[\s\S]*?radial-gradient[\s\S]*?optical-glass-highlight-color/)
    expect(opticalGlassCss).toMatch(/\.optical-glass::before\s*\{[\s\S]*?radial-gradient\(\s*54% 24% at 12% 0%/)
    expect(opticalGlassCss).toMatch(/\.optical-glass::before\s*\{[\s\S]*?radial-gradient/)
    expect(opticalGlassCss).toMatch(/\.optical-glass::after\s*\{[\s\S]*?optical-glass-refraction-color/)
    expect(opticalGlassCss).not.toContain('conic-gradient')
    expect(opticalGlassCss).not.toContain('mask-composite')
  })

  it('mounts every confirmed runtime glass surface on the shared primitive', () => {
    expect(shellCss).toContain('.workspace-drawer.optical-glass')
    expect(contextSource).toContain('class="context-menu-panel optical-glass"')
    expect(selectionSource).toContain('class="selection-card optical-glass"')
    expect(appSource).toContain('class="thread-jump-latest optical-glass"')
    expect(appSource).toContain('class="core-goal-area optical-glass"')
    expect(mobileSource).toContain('class="mobile-top-bar__button mobile-command-dock__trigger"')
    expect(mobileSource).not.toContain('class="mobile-top-bar__button mobile-command-dock__trigger optical-glass"')
    expect(mobileSource).toContain('class="mobile-top-bar__sync optical-glass"')
    expect(mobileSource).toContain('class="mobile-command-dock__panel optical-glass"')
    expect(mobileSource).toContain('--text: var(--theme-main-text);')
    expect(catalogSource).toContain("'optical-glass': variant === 'popover'")
    expect(runtimeDockSource).toContain('class="wf-node-runtime optical-glass"')
  })

  it('does not duplicate the substrate filter on consumers', () => {
    const goalRule = layoutCss.match(/\.core-goal-area\s*\{[\s\S]*?\n\}/)?.[0] || ''
    const jumpRule = appSource.match(/\.thread-jump-latest\s*\{[\s\S]*?\n\}/)?.[0] || ''
    expect(goalRule).not.toContain('backdrop-filter')
    expect(jumpRule).not.toContain('backdrop-filter')
    expect(contextSource).not.toContain('backdrop-filter')
    expect(mobileSource).not.toContain('backdrop-filter')
    expect(selectionSource).not.toContain('backdrop-filter')
    expect(catalogSource).not.toContain('backdrop-filter')
    expect(runtimeDockSource).not.toContain('backdrop-filter')
  })

  it('keeps interactive glass motion subtle and reduced-motion safe', () => {
    expect(mobileSource).toMatch(/\.mobile-top-bar__button:hover\s*\{[\s\S]*?brightness\(1\.015\)/)
    expect(mobileSource).toMatch(/\.mobile-top-bar__button:active\s*\{[\s\S]*?scale\(\.98\)/)
    expect(appSource).toMatch(/\.thread-jump-latest:hover\s*\{[\s\S]*?brightness\(1\.015\)/)
    expect(appSource).toMatch(/\.thread-jump-latest:active\s*\{[\s\S]*?scale\(\.98\)/)
    expect(mobileSource).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.mobile-top-bar__button\s*\{[\s\S]*?transition: none/)
    expect(appSource).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.thread-jump-latest,/)
  })
})
