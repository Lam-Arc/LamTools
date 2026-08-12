import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const packageRoot = resolve(import.meta.dirname, '..')
const packageJson = JSON.parse(readFileSync(resolve(packageRoot, 'package.json'), 'utf8'))
const viteConfig = readFileSync(resolve(packageRoot, 'vite.config.ts'), 'utf8')
const demoApp = readFileSync(resolve(packageRoot, 'src/demo/App.vue'), 'utf8')
const layoutCss = readFileSync(resolve(packageRoot, 'src/styles/layout.css'), 'utf8')

describe('Core UI package boundary', () => {
  it('builds declarations after the library output so the public type entry remains in dist', () => {
    expect(packageJson.scripts.build).toContain('vite build && vue-tsc -b')
    expect(packageJson.scripts.build).toContain('tsconfig.demo.json')
    expect(packageJson.scripts.typecheck).toContain('tsconfig.demo.json')
    expect(packageJson.types).toBe('./dist/index.d.ts')
    expect(packageJson.exports['.'].types).toBe('./dist/index.d.ts')
  })

  it('exports the CSS file emitted by the library build', () => {
    expect(packageJson.exports['./styles']).toBe('./dist/lamtools-ui.css')
  })

  it('proxies the Core app-server websocket in local GUI mode', () => {
    expect(viteConfig).toMatch(/['"]\/api['"]:[\s\S]*ws:\s*true/)
    expect(viteConfig).toContain("process.env.CORE_BACKEND_PORT || '5172'")
  })

  it('wires the generic Agent workbench controllers into the Core app itself', () => {
    expect(demoApp).toMatch(/useCoreLiveComposerController/)
    expect(demoApp).toMatch(/useCoreWorkbenchProjectionController/)
    expect(demoApp).toMatch(/useCoreApprovalController/)
    expect(demoApp).toMatch(/useCoreQueuedInputController/)
    expect(demoApp).toMatch(/useCoreExecutionControlsState/)
    expect(demoApp).toMatch(/useCoreAutoFollowScroll/)
    expect(demoApp).toMatch(/<CoreQueuedInputTray/)
    expect(demoApp).toMatch(/<CommandPalette/)
    expect(demoApp).toMatch(/@decision-select=/)
    expect(demoApp).toMatch(/<CoreSessionTitleEditor/)
    expect(demoApp).not.toMatch(/allow-rename/)
    expect(demoApp).not.toMatch(/@rename-session=/)
    expect(demoApp).toMatch(/@delete-session="deleteSession"/)
    expect(demoApp).toMatch(/:allow-session-delete="!workflowMode"/)
    expect(demoApp).not.toMatch(/coreAppItemToMessagePart/)
  })

  it('keeps the shared composer inside the main workspace when a narrow viewport still has a pinned sidebar', () => {
    expect(layoutCss).toMatch(/@media \(max-width: 820px\)[\s\S]*?\.floating-composer \{ width: var\(--composer-full-width\); \}/)
    expect(layoutCss).toMatch(/\.send \{[\s\S]*?flex: 0 0 54px;/)
    expect(layoutCss).toMatch(/\.drawer-right:not\(\.open\) \{ opacity: 0; pointer-events: none; \}/)
  })

  it('keeps the right runtime toolbar reachable below 640px', () => {
    const mobileCss = layoutCss.match(/@media \(max-width: 640px\) \{([\s\S]*?)@media \(max-width: 480px\)/)?.[1] || ''
    const shellSource = readFileSync(resolve(packageRoot, 'src/components/WorkspaceShell.vue'), 'utf8')

    expect(mobileCss).toContain('--right-drawer-width: 100vw')
    expect(mobileCss).not.toMatch(/\.drawer-right \{[^}]*display: none/)
    // The drawer hides through opacity/pointer-events, and the mobile nav keeps
    // a dedicated right-panel toggle so the runtime toolbar stays reachable
    expect(layoutCss).toMatch(/\.drawer-right:not\(\.open\) \{ opacity: 0; pointer-events: none; \}/)
    expect(shellSource).toMatch(/data-mobile-right-toggle/)
  })
})
