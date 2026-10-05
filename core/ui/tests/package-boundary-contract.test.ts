import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const packageRoot = resolve(import.meta.dirname, '..')
const packageJson = JSON.parse(readFileSync(resolve(packageRoot, 'package.json'), 'utf8'))
const viteConfig = readFileSync(resolve(packageRoot, 'vite.config.ts'), 'utf8')
const appSource = readFileSync(resolve(packageRoot, 'src/app/LamToolsApp.vue'), 'utf8')
const runtimeSource = readFileSync(resolve(packageRoot, 'src/app/runtime.ts'), 'utf8')
const workbenchSource = readFileSync(resolve(packageRoot, 'src/workbench/createWorkbench.ts'), 'utf8')
const bundledPlugins = readFileSync(resolve(packageRoot, 'src/plugins/bundled.ts'), 'utf8')
const layoutCss = readFileSync(resolve(packageRoot, 'src/styles/layout.css'), 'utf8')
const workspaceShellCss = readFileSync(resolve(packageRoot, 'src/styles/workspace-shell.css'), 'utf8')
const shellSource = readFileSync(resolve(packageRoot, 'src/components/WorkspaceShell.vue'), 'utf8')

describe('Core UI package boundary', () => {
  it('builds declarations after the library output so the public type entry remains in dist', () => {
    expect(packageJson.scripts.build).toContain('vite build && vue-tsc -b')
    expect(packageJson.scripts.build).not.toContain('tsconfig.demo.json')
    expect(packageJson.scripts.typecheck).not.toContain('tsconfig.demo.json')
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
    expect(runtimeSource).toContain('createWorkbench')
    expect(workbenchSource).toMatch(/useCoreLiveComposerController/)
    expect(workbenchSource).toMatch(/useCoreWorkbenchProjectionController/)
    expect(workbenchSource).toMatch(/useCoreApprovalController/)
    expect(workbenchSource).toMatch(/useCoreQueuedInputController/)
    expect(appSource).toMatch(/workbench\.composer/)
    expect(appSource).toMatch(/workbench\.approval/)
    expect(appSource).toMatch(/workbench\.queue/)
    expect(appSource).toMatch(/useCoreExecutionControlsState/)
    expect(appSource).toMatch(/useCoreAutoFollowScroll/)
    expect(appSource).toMatch(/<CoreQueuedInputTray/)
    expect(appSource).toMatch(/<CommandPalette/)
    expect(appSource).toMatch(/@decision-select=/)
    expect(appSource).toMatch(/<CoreSessionTitleEditor/)
    expect(appSource).not.toMatch(/allow-rename/)
    expect(appSource).toMatch(/@rename-session="renameSessionFromSidebar"/)
    expect(appSource).toMatch(/@delete-session="deleteSession"/)
    expect(appSource).toMatch(/:allow-session-delete="sidebarAllowSessionDelete"/)
    expect(appSource).not.toContain('workflowMode')
    expect(appSource).toMatch(/@export-session="exportSession"/)
    expect(appSource).not.toMatch(/coreAppItemToMessagePart/)
  })

  it('keeps low-frequency workspaces out of the desktop startup chunk', () => {
    expect(appSource).toContain("defineAsyncComponent(() => import('../components/CoreSettings.vue'))")
    expect(appSource).toContain('<PluginModeHost')
    expect(appSource).not.toContain('WorkflowCanvas.vue')
    expect(bundledPlugins).toContain("'workflow:workflow': () => import('@lamtools/bundled-workflow-ui')")
    // 视窗已归档：主程序不再挂载 StagePane，组件只留在归档目录里。
    expect(appSource).not.toContain('StagePane')
    expect(appSource).not.toContain('workspace-stage')
  })

  it('keeps the shared composer inside the main workspace when a narrow viewport still has a pinned sidebar', () => {
    expect(layoutCss).toMatch(/@media \(max-width: 820px\)[\s\S]*?\.floating-composer \{ width: var\(--composer-full-width\); \}/)
    expect(layoutCss).toMatch(/\.send \{[\s\S]*?flex: 0 0 54px;/)
    expect(workspaceShellCss).toMatch(/\.drawer-right:not\(\.open\) \{[^}]*visibility: hidden;[^}]*pointer-events: none;/)
  })

  it('keeps the right runtime toolbar reachable below 640px', () => {
    const mobileCss = workspaceShellCss.match(/@media \(max-width: 640px\) \{([\s\S]*)/)?.[1] || ''

    expect(mobileCss).toContain('--right-drawer-width: 100vw')
    expect(mobileCss).not.toMatch(/\.drawer-right \{[^}]*display: none/)
    // The drawer hides through delayed visibility/pointer-events and is opened by the
    // matching screen-edge swipe on narrow touch surfaces.
    expect(workspaceShellCss).toMatch(/\.drawer-right:not\(\.open\) \{[^}]*visibility: hidden;[^}]*pointer-events: none;/)
    expect(mobileCss).toContain('touch-action: pan-y')
    expect(shellSource).toContain('@pointerdown="onSwipePointerDown"')
    expect(shellSource).toContain('SWIPE_TRIGGER_DISTANCE')
  })

  it('keeps the mobile right rail liquid glass while retaining the left drawer surface', () => {
    const mobileCss = workspaceShellCss.match(/@media \(max-width: 640px\) \{([\s\S]*)/)?.[1] || ''

    const genericDrawerRule = mobileCss.match(/\.workspace-drawer\s*\{([^}]*)\}/)?.[1] || ''
    expect(genericDrawerRule).not.toMatch(/background:/)
    expect(mobileCss).toMatch(/\.drawer-left\s*\{[\s\S]*?background: var\(--theme-backdrop-background\);[\s\S]*?box-shadow: 0 4px 12px rgba\(0, 0, 0, \.22\);/)
    expect(shellSource).toContain('class="workspace-drawer drawer-right optical-glass"')
    expect(workspaceShellCss).not.toContain('.drawer-right::before')
  })
})
