import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const appSource = readFileSync(resolve(import.meta.dirname, '../src/App.vue'), 'utf8')
const shellSource = readFileSync(resolve(import.meta.dirname, '../../ui/src/app/LamToolsApp.vue'), 'utf8')

describe('mobile command dock host contract', () => {
  it('routes mode selection and shared app surfaces through the floating dock', () => {
    expect(appSource).toContain(':mode-options="mobileModeState.options"')
    expect(appSource).toContain(':active-mode-id="mobileModeState.activeId"')
    expect(appSource).toContain('@select-mode="lamToolsAppRef?.selectAppModeByKey($event)"')
    expect(appSource).toContain('@open-search="lamToolsAppRef?.openSearch()"')
    expect(appSource).toContain('@open-settings="lamToolsAppRef?.openSettings()"')
    expect(appSource).toContain('@open-account="accessPanelOpen = true"')
  })

  it('shows the active account identity without making login mandatory', () => {
    expect(appSource).toContain("accountClient.value?.session?.username || '登录 / 账号'")
    expect(appSource).toContain('accessPanelOpen.value = false')
  })

  it('refreshes server-provided modes when the runtime changes', () => {
    expect(appSource).toContain('await lamToolsAppRef.value?.refreshPluginModes()')
  })

  it('uses a device-transfer icon for project synchronization', () => {
    expect(shellSource).toContain('<MonitorSmartphone :size="17"')
    expect(shellSource).not.toMatch(/data-sidebar-sync-project[\s\S]{0,200}<RefreshCw/)
  })

  it('removes the desktop main-card frame on the mobile viewport', () => {
    expect(appSource).toMatch(/\.mobile-host \.workspace-main \{[\s\S]*?border: 0;[\s\S]*?border-radius: 0;[\s\S]*?box-shadow: none;/)
  })
})
