import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../src/pairing/PairingScreen.vue', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const syncSource = readFileSync(new URL('../src/sync/MobileSyncPanel.vue', import.meta.url), 'utf8')
const templateEnd = source.indexOf('\n</template>\n\n<script setup')
const template = source.slice(source.indexOf('<template>'), templateEnd + '\n</template>'.length)

describe('PairingScreen account entry', () => {
  it('keeps the default account card limited to credentials and authentication actions', () => {
    const moreStart = template.indexOf('<section v-if="moreOpen"')
    const defaultView = template.slice(0, moreStart)
    const advancedView = template.slice(moreStart)

    expect(defaultView).toContain('autocomplete="username"')
    expect(defaultView).toContain(":autocomplete=\"authMode === 'login' ? 'current-password' : 'new-password'\"")
    expect(defaultView).toContain('确认登录')
    expect(defaultView).toContain('转到注册')
    expect(defaultView).not.toContain('id="pairing-code"')
    expect(defaultView).not.toContain('id="gateway-url"')
    expect(advancedView).toContain('id="pairing-code"')
    expect(advancedView).toContain('id="gateway-url"')
    expect(advancedView).toContain('id="server-url"')
  })

  it('keeps advanced connection methods behind the More disclosure', () => {
    expect(template).toContain(':aria-expanded="moreOpen"')
    expect(template).toContain('@click="moreOpen = !moreOpen"')
    expect(template).toContain('<section v-if="moreOpen"')
  })

  it('supports a non-dismissible first-login card', () => {
    expect(template).toContain('v-if="closable"')
  })

  it('replaces the login card title when registration is selected', () => {
    expect(template).toContain("authMode === 'login' ? '登录 LamTools' : '注册 LamTools'")
    expect(source).toContain('normalizedUsername.length >= 3')
    expect(source).toContain('normalizedUsername.length <= 32')
  })

  it('shows the signed-in account device topology before advanced pairing controls', () => {
    const devices = template.indexOf('设备与工作环境')
    const more = template.indexOf('pairing-screen__more-toggle')

    expect(devices).toBeGreaterThan(-1)
    expect(devices).toBeLessThan(more)
    expect(template).toContain("device.online ? '在线' : '离线'")
    expect(template).toContain("$emit('workspace-select', device.workspaceId)")
  })

  it('shares the mobile host account state and actions with Core settings', () => {
    expect(appSource).toContain(':account-context="accountContext"')
    expect(appSource).toContain('@account-submit="authenticateCoreAccount"')
    expect(appSource).toContain('@account-logout="logoutAccount"')
  })

  it('starts in standalone mode without forcing the account panel open', () => {
    expect(appSource).toContain("const activeRuntimeMode = ref<'local' | 'remote'>('local')")
    expect(appSource).toContain('const accessPanelOpen = ref(false)')
    expect(appSource).toContain(':closable="true"')
    expect(appSource).not.toContain('accessPanelOpen.value = !activeTrustedDevice.value')
  })

  it('routes account and paired-device choices through the explicit sync flow', () => {
    expect(appSource).toContain('@workspace-select="openWorkspaceSync"')
    expect(appSource).toContain('@select-device="openDeviceSync"')
    expect(appSource).toContain('@sync-request="openSyncPanel()"')
    expect(syncSource).toContain("value=\"remote\" :disabled=\"busy || selectedDevice?.online === false\"")
    expect(syncSource).toContain('设备下线后不可用')
    expect(syncSource).toContain('将项目与会话复制到手机')
  })

  it('groups account workspaces by host and isolates cached projects by account', () => {
    expect(appSource).toContain('`account-device:${hostKey}`')
    expect(appSource).toContain("accountWorkspaces.value.filter((workspace) => (")
    expect(appSource).toContain("await syncRepository.setAccountScope(session?.serverId || '', session?.username || '')")
    expect(appSource).toContain("await remoteRepository.setAccountScope(session?.serverId || '', session?.username || '')")
    expect(appSource).toContain('const syncProjectTargets = new Map')
  })

  it('requires a completed remote sync before opening the selected project', () => {
    const disconnect = appSource.indexOf('runtime.workbench.disconnect()')
    const switchTransport = appSource.indexOf('await transport.use(connectionManager.getTransport())', disconnect)
    const start = appSource.indexOf('await syncEngine.start()')
    const open = appSource.indexOf('await lamToolsAppRef.value?.openProject(projectId)', start)

    expect(disconnect).toBeGreaterThan(-1)
    expect(switchTransport).toBeGreaterThan(disconnect)
    expect(start).toBeGreaterThan(-1)
    expect(open).toBeGreaterThan(start)
    expect(appSource).toContain("if (syncEngine.state.value !== 'synced')")
    expect(appSource).toContain("throw new Error(`会话历史游标重复：${thread.title}`)")
  })

  it('persists offline sync devices and disables stale remote access after restart', () => {
    expect(appSource).toContain('SYNC_OFFLINE_DEVICES_STORAGE_KEY')
    expect(appSource).toContain('readSyncOfflineDeviceIds()')
    expect(appSource).toContain('setSyncDeviceOffline(payload.deviceId, true)')
    expect(appSource).toContain('`account:${server}:${account}:${deviceId}`')
  })

  it('imports history by the source project id and cancels stale project loads', () => {
    expect(appSource).toContain('thread.projectId === projectId')
    expect(appSource).toContain('class SyncLoadCancelledError extends Error')
    expect(appSource).toContain('prepareSyncDevice(deviceId, workspace?.workspaceId || \'\', generation)')
  })

  it('keeps only the system inset above chat and shifts drawer content below controls', () => {
    expect(appSource).toContain(
      '--mobile-header-offset: max(var(--native-safe-area-top, 0px), env(safe-area-inset-top, 0px))',
    )
    expect(appSource).toContain('background: var(--theme-main-background)')
    expect(appSource).toContain("'mobile-host--left-drawer-open': leftDrawerOpen")
    expect(appSource).toContain('.mobile-host--left-drawer-open::before')
    expect(appSource).toContain('background: var(--theme-backdrop-background)')
    expect(appSource).toMatch(/\.mobile-host \.workspace-main \{[\s\S]*?padding-top: calc\(var\(--space-6\) \+ var\(--space-1\)\);[\s\S]*?border: 0;/)
    expect(appSource).toContain('.mobile-host .drawer-left { padding-top: var(--space-4); }')
  })
})
