import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const appSource = readFileSync(resolve(import.meta.dirname, '../src/App.vue'), 'utf8')
const shellSource = readFileSync(resolve(import.meta.dirname, '../../ui/src/app/LamToolsApp.vue'), 'utf8')
const topBarSource = readFileSync(resolve(import.meta.dirname, '../../ui/src/components/MobileTopBar.vue'), 'utf8')

describe('mobile command dock host contract', () => {
  it('routes mode selection and shared app surfaces through the floating dock', () => {
    expect(appSource).toContain(':mode-options="mobileModeState.options"')
    expect(appSource).toContain(':active-mode-id="mobileModeState.activeId"')
    expect(appSource).toContain('@select-mode="lamToolsAppRef?.selectAppModeByKey($event)"')
    expect(appSource).toContain('@open-search="lamToolsAppRef?.openSearch()"')
    expect(appSource).toContain('@open-settings="lamToolsAppRef?.openSettings()"')
    expect(appSource).toContain(':mobile-command-dock-available="mobileCommandDockAvailable"')
    expect(appSource).toContain(':available="mobileCommandDockAvailable"')
    expect(appSource).not.toContain(':mobile-top-bar-hidden=')
    expect(appSource).toContain('@open-account="accessPanelOpen = true"')
    expect(appSource).toContain('@open-plugins="lamToolsAppRef?.openPlugins()"')
    expect(appSource).toContain('@open-arrange="lamToolsAppRef?.openArrange()"')
  })

  it('keeps narrow drawers simplified while restoring all wide Pad actions', () => {
    expect(shellSource).toContain("const showMobileFooterFallback = computed(() => appRuntime.platform === 'mobile' && props.mobileCommandDockAvailable !== true)")
    expect(shellSource).toContain(':show-sidebar-search-action="appRuntime.platform !== \'mobile\' || showMobileFooterFallback"')
    expect(shellSource).toContain(':show-sidebar-plugins-action="appRuntime.platform !== \'mobile\' || showMobileFooterFallback"')
    expect(shellSource).toContain(':show-sidebar-settings-action="appRuntime.platform !== \'mobile\' || showMobileFooterFallback"')
    expect(shellSource).toContain('v-if="showSidebarFooter" #sidebar-footer')
    expect(shellSource).toContain('v-if="appRuntime.platform !== \'mobile\' || showMobileFooterFallback" class="sidebar-action" type="button" data-mobile-footer-arrange')
    expect(shellSource).toContain('@click="selectAppModeByKey(option.id)"')
    expect(shellSource).toContain('@click="emit(\'open-account\')"')
    expect(shellSource).toContain('openPlugins,')
    expect(shellSource).toContain('openArrange() { showArrange.value = true }')
  })

  it('tracks the narrow dock breakpoint and removes its listener on unmount', () => {
    const availability = readFileSync(resolve(import.meta.dirname, '../src/useMobileCommandDockAvailability.ts'), 'utf8')
    expect(availability).toContain("'(max-width: 640px)'")
    expect(availability).toContain("addEventListener('change', update)")
    expect(availability).toContain("removeEventListener('change', update)")
    expect(topBarSource).toContain('v-show="available && !hidden"')
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

  it('disables the desktop right rail and preserves the full-height left drawer', () => {
    expect(shellSource).toContain(':show-right-panel="appRuntime.platform !== \'mobile\'"')
    expect(appSource).toContain('active.blur()')
    expect(appSource).toMatch(/\.mobile-host \.drawer-left \{[\s\S]*?height: 100dvh;/)
  })
})
