<template>
  <main class="mobile-host">
    <LamToolsApp
      ref="lamToolsAppRef"
      :runtime="runtime"
      :account-context="accountContext"
      @left-drawer-change="leftDrawerOpen = $event"
      @account-submit="authenticateCoreAccount"
      @account-logout="logoutAccount"
    />
    <MobileTopBar
      :hidden="topBarHidden"
      :syncing="isSyncing"
      @open-sidebar="openLeftSidebar"
      @open-account="accessPanelOpen = true"
    />
    <div v-if="accessPanelOpen" class="mobile-access-overlay">
      <PairingScreen
        :closable="Boolean(accountClient?.session || activeTrustedDevice)"
        :current-device="activeTrustedDevice"
        :trusted-devices="trustedDevices"
        :account-session="accountClient?.session || null"
        :account="accountClient"
        :workspaces="accountWorkspaces"
        :account-nodes="accountNodes"
        :account-loading="accountLoading"
        :account-error="accountError"
        :gateway-url="manualGatewayUrl"
        @close="closeAccessPanel"
        @paired="handlePaired"
        @select-device="selectTrustedDevice"
        @forget-device="forgetDevice"
        @gateway-url-change="setManualGatewayUrl"
        @account-authenticate="authenticateAccount"
        @workspace-select="selectWorkspace"
        @account-logout="logoutAccount"
      />
    </div>
    <p v-if="statusMessage" class="mobile-host-status" role="status">{{ statusMessage }}</p>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { Capacitor } from '@capacitor/core'
import { createCoreProjectClient, createLamToolsRuntime, MobileTopBar, type MobileControlAccountContext, type MobileControlAccountDevice, type MobileControlAccountPayload } from '@lamtools/ui'
import LamToolsApp from '@lamtools/ui/app/LamToolsApp.vue'
import { AccountClient, loadStoredAccount, normalizeProfile, type AccountNode, type AccountWorkspace } from './account'
import { ConnectionManager } from './connection/ConnectionManager'
import {
  forgetTrustedDevice,
  listTrustedDevices,
  type TrustedDevice,
} from './pairing/TrustedDevices'
import { onMobileResume } from './native/lifecycle'
import { createMobileFilePicker } from './native/filePicker'
import { loadOrCreateDeviceIdentity, type DeviceIdentity } from './pairing/DeviceIdentity'
import PairingScreen, {
  type AccountAuthRequest,
} from './pairing/PairingScreen.vue'
import { createLocalFirstProjectClient, createLocalRepository } from './storage'
import { SyncEngine } from './sync'

const MANUAL_GATEWAY_STORAGE_KEY = 'lamtools.mobile.manual-gateway-v1'
const DEFAULT_SERVER_URL = 'wss://47.114.43.99.nip.io/v1/relay'

const statusMessage = ref('')
const lamToolsAppRef = ref<InstanceType<typeof LamToolsApp> | null>(null)
const accessPanelOpen = ref(true)
const leftDrawerOpen = ref(false)
const topBarHidden = computed(() => leftDrawerOpen.value || accessPanelOpen.value)
const activeTrustedDevice = ref<TrustedDevice | null>(null)
const trustedDevices = ref<TrustedDevice[]>([])
const accountClient = shallowRef<AccountClient | null>(null)
const accountWorkspaces = ref<AccountWorkspace[]>([])
const accountNodes = ref<AccountNode[]>([])
const accountLoading = ref(false)
const accountError = ref('')
const manualGatewayUrl = ref(readManualGatewayUrl())
const activeWorkspaceId = ref('')
const activeWorkspaceName = ref('')
const identity = ref<DeviceIdentity | null>(null)
const accountDevices = computed<MobileControlAccountDevice[]>(() => accountNodes.value
  .filter((node) => !node.revokedAtMs)
  .map((node) => {
    const workspace = accountWorkspaces.value.find((item) => item.hostNodeId === node.nodeId)
    const currentMobile = node.nodeId === accountClient.value?.session?.nodeId
    const active = node.nodeId === activeTrustedDevice.value?.deviceId
    return {
      nodeId: node.nodeId,
      label: workspace?.displayName || node.displayName,
      detail: active
        ? '当前控制的工作环境'
        : currentMobile
          ? '当前移动设备'
          : (workspace ? '桌面端工作环境' : '移动设备'),
      platform: node.platform,
      online: currentMobile || active || workspace?.online === true,
      current: currentMobile || active,
    }
  })
  .sort((left, right) => Number(right.current) - Number(left.current) || Number(right.online) - Number(left.online)))
const accountContext = computed<MobileControlAccountContext>(() => {
  const session = accountClient.value?.session
  return {
    status: session ? {
      baseUrl: session.baseUrl,
      serverId: session.serverId,
      username: session.username,
      nodeId: session.nodeId,
      accessExpiresAtMs: session.accessExpiresAtMs,
      refreshExpiresAtMs: session.refreshExpiresAtMs,
    } : null,
    devices: accountDevices.value,
    loading: accountLoading.value,
    error: accountError.value,
  }
})
const workspaceOptions = computed(() => {
  const accountOptions = accountWorkspaces.value.map((workspace) => ({
    id: `workspace:${workspace.workspaceId}`,
    label: workspace.displayName,
    online: workspace.online,
    platform: workspace.host?.platform || 'desktop',
    deviceName: workspace.host?.displayName,
  }))
  const directOptions = trustedDevices.value.map((device) => ({
    id: `device:${device.deviceId}`,
    label: device.name,
    online: true,
    platform: device.platform || 'desktop',
    deviceName: '可信设备',
  }))
  return [...accountOptions, ...directOptions]
})
const activeControlId = computed(() => activeWorkspaceId.value
  ? `workspace:${activeWorkspaceId.value}`
  : (activeTrustedDevice.value ? `device:${activeTrustedDevice.value.deviceId}` : ''))

const connectionManager = new ConnectionManager({
  relayEndpoint: import.meta.env.VITE_LAMTOOLS_RELAY_URL,
})
const repository = createLocalRepository()
const runtime = createLamToolsRuntime({
  transport: connectionManager.getTransport(),
  platform: 'mobile',
  sessions: {
    listSessions: () => repository.listSessions(),
  },
  projectClient: createLocalFirstProjectClient(
    createCoreProjectClient(connectionManager.getTransport()),
    repository,
  ),
  capabilities: {
    filePicker: true,
    notifications: Capacitor.isNativePlatform(),
    desktopWindow: false,
    files: createMobileFilePicker(),
  },
  workspaceControl: {
    activeId: activeControlId,
    options: workspaceOptions,
    async select(id: string) {
      if (id.startsWith('workspace:')) await selectWorkspace(id.slice('workspace:'.length))
      else if (id.startsWith('device:')) await selectTrustedDevice(id.slice('device:'.length))
    },
  },
})
const syncEngine = new SyncEngine({
  transport: connectionManager.getTransport(),
  repository,
  requestRpc: (method, params, timeoutMs) => runtime.requestRpc(method, params, timeoutMs),
  onError: (message) => { statusMessage.value = `同步失败：${message}` },
})
const isSyncing = computed(() => syncEngine.state.value === 'syncing')
watch(syncEngine.state, (state) => {
  if (state === 'synced') statusMessage.value = ''
})
const removeRepositoryListener = repository.subscribe(() => {
  void Promise.all([
    runtime.workbench.refreshSessions(),
    Promise.resolve().then(() => window.dispatchEvent(new CustomEvent('lamtools:projects-synced'))),
  ])
})

function startSync(): void {
  void syncEngine.start().catch((error) => {
    statusMessage.value = error instanceof Error ? error.message : String(error)
  })
}

function openLeftSidebar(): void {
  lamToolsAppRef.value?.openLeftSidebar()
}

function closeAccessPanel(): void {
  if (activeTrustedDevice.value) accessPanelOpen.value = false
}

async function handlePaired(device: TrustedDevice): Promise<void> {
  activeWorkspaceId.value = ''
  activeWorkspaceName.value = ''
  activeTrustedDevice.value = device
  await connectionManager.setConnectionContext({ account: accountClient.value, workspaceId: '', trustedDevice: device })
  accessPanelOpen.value = false
  accountError.value = ''
  statusMessage.value = ''
  await repository.setDesktopId(device.deviceId)
  await repository.setWorkspaceId('')
  startSync()
}

async function selectTrustedDevice(deviceId: string): Promise<void> {
  const device = trustedDevices.value.find((item) => item.deviceId === deviceId)
  if (!device) return
  activeWorkspaceId.value = ''
  activeWorkspaceName.value = ''
  activeTrustedDevice.value = device
  await connectionManager.setConnectionContext({ account: accountClient.value, workspaceId: '', trustedDevice: device })
  accessPanelOpen.value = false
  statusMessage.value = ''
  await repository.setDesktopId(device.deviceId)
  await repository.setWorkspaceId('')
  startSync()
}

async function forgetDevice(deviceId: string): Promise<void> {
  try {
    await forgetTrustedDevice(deviceId)
    trustedDevices.value = trustedDevices.value.filter((device) => device.deviceId !== deviceId)
    if (activeTrustedDevice.value?.deviceId === deviceId && !activeWorkspaceId.value) {
      activeTrustedDevice.value = null
      connectionManager.setTrustedDevice(null)
      runtime.close()
      accessPanelOpen.value = true
    }
    statusMessage.value = '已忘记这台电脑'
  } catch (error) {
    statusMessage.value = error instanceof Error ? error.message : String(error)
  }
}

function setManualGatewayUrl(value: string): void {
  manualGatewayUrl.value = value.trim()
  try {
    globalThis.localStorage?.setItem(MANUAL_GATEWAY_STORAGE_KEY, manualGatewayUrl.value)
  } catch {
    // Native webviews may not expose localStorage. The field remains usable
    // for the current process in that case.
  }
}

async function authenticateAccount(request: AccountAuthRequest): Promise<void> {
  accountLoading.value = true
  accountError.value = ''
  try {
    const profile = normalizeProfile(
      request.serverUrl || import.meta.env.VITE_LAMTOOLS_RELAY_URL || DEFAULT_SERVER_URL,
    )
    const client = new AccountClient({ profile })
    if (request.mode === 'register') {
      await client.register(request.username, request.password)
    } else {
      await client.login(request.username, request.password)
    }
    accountClient.value = client
    connectionManager.setAccount(client)
    await loadWorkspaces(client)
    startAccountDiscovery()
    statusMessage.value = `已登录 ${client.session?.username || request.username}`
  } catch (error) {
    accountError.value = error instanceof Error ? error.message : String(error)
  } finally {
    accountLoading.value = false
  }
}

function authenticateCoreAccount(payload: MobileControlAccountPayload): void {
  void authenticateAccount({
    mode: payload.mode,
    serverUrl: payload.baseUrl,
    username: payload.username,
    password: payload.password,
  })
}

async function loadWorkspaces(client: AccountClient): Promise<void> {
  const [workspaces, nodes] = await Promise.all([
    client.listWorkspaces(),
    client.listNodes(),
  ])
  accountWorkspaces.value = workspaces
  accountNodes.value = nodes
  const preferred = client.session?.selectedWorkspaceId
  const selected = (preferred && workspaces.find((item) => item.workspaceId === preferred))
    || workspaces.find((item) => item.online)
    || workspaces[0]
  if (selected && selected.host?.publicKey) {
    if (activeWorkspaceId.value !== selected.workspaceId
      || activeTrustedDevice.value?.deviceId !== selected.hostNodeId) {
      await activateWorkspace(selected)
    }
  }
}

let accountDiscoveryTimer: ReturnType<typeof setInterval> | null = null
let accountDiscoveryRunning = false

function startAccountDiscovery(): void {
  if (accountDiscoveryTimer || !accountClient.value) return
  accountDiscoveryTimer = setInterval(() => {
    const client = accountClient.value
    if (!client || accountDiscoveryRunning) return
    accountDiscoveryRunning = true
    void loadWorkspaces(client)
      .catch((error) => {
        accountError.value = error instanceof Error ? error.message : String(error)
      })
      .finally(() => { accountDiscoveryRunning = false })
  }, 3_000)
}

function stopAccountDiscovery(): void {
  if (accountDiscoveryTimer) clearInterval(accountDiscoveryTimer)
  accountDiscoveryTimer = null
  accountDiscoveryRunning = false
}

async function selectWorkspace(workspaceId: string): Promise<void> {
  const workspace = accountWorkspaces.value.find((item) => item.workspaceId === workspaceId)
  if (!workspace || !accountClient.value) return
  if (!workspace.host?.publicKey) {
    accountError.value = '服务器未返回该工作环境的设备公钥，无法建立安全连接'
    return
  }
  await activateWorkspace(workspace)
}

async function activateWorkspace(workspace: AccountWorkspace): Promise<void> {
  const client = accountClient.value
  const host = workspace.host
  if (!client || !host?.publicKey) return
  const device: TrustedDevice = {
    deviceId: workspace.hostNodeId,
    name: workspace.displayName || host.displayName,
    platform: host.platform,
    publicKey: host.publicKey,
    relayUrl: client.getRelayEndpoint(),
  }
  await client.selectWorkspace(workspace.workspaceId)
  activeWorkspaceId.value = workspace.workspaceId
  activeWorkspaceName.value = workspace.displayName
  activeTrustedDevice.value = device
  await connectionManager.setConnectionContext({
    account: client,
    workspaceId: workspace.workspaceId,
    trustedDevice: device,
  })
  await repository.setWorkspaceId(workspace.workspaceId)
  await repository.setDesktopId(device.deviceId)
  accessPanelOpen.value = false
  accountError.value = ''
  statusMessage.value = workspace.online ? '' : '工作环境当前离线，已保留本地缓存'
  startSync()
}

async function logoutAccount(): Promise<void> {
  stopAccountDiscovery()
  const client = accountClient.value
  accountClient.value = null
  accountWorkspaces.value = []
  accountNodes.value = []
  activeWorkspaceId.value = ''
  activeWorkspaceName.value = ''
  connectionManager.setAccount(null)
  connectionManager.setWorkspace('')
  await repository.setWorkspaceId('')
  if (activeTrustedDevice.value && !activeTrustedDevice.value.accessToken) {
    activeTrustedDevice.value = null
    connectionManager.setTrustedDevice(null)
    runtime.close()
  }
  if (client) await client.logout()
  statusMessage.value = '已退出服务器账号'
}

async function restoreActiveConnection(): Promise<void> {
  if (accessPanelOpen.value) return
  connectionManager.prepareForResume()
  try {
    const activeSessionId = runtime.workbench.activeSessionId.value
    if (activeSessionId) await runtime.workbench.connect(activeSessionId)
    await runtime.workbench.refreshSessions()
  } catch (error) {
    statusMessage.value = error instanceof Error ? error.message : String(error)
  }
}

async function initialize(): Promise<void> {
  try {
    const loadedIdentity = await loadOrCreateDeviceIdentity()
    identity.value = loadedIdentity
    connectionManager.setDeviceId(loadedIdentity.deviceId)
    await connectionManager.startNetworkMonitoring()

    const restoredAccount = await loadStoredAccount()
    if (restoredAccount) {
      accountClient.value = restoredAccount
      connectionManager.setAccount(restoredAccount)
      try {
        await loadWorkspaces(restoredAccount)
        startAccountDiscovery()
      } catch (error) {
        accountError.value = error instanceof Error ? error.message : String(error)
      }
    }

    trustedDevices.value = await listTrustedDevices()
    if (!activeTrustedDevice.value && trustedDevices.value[0]) {
      const first = trustedDevices.value[0]
      activeTrustedDevice.value = first
      connectionManager.setWorkspace('')
      connectionManager.setTrustedDevice(first)
      await repository.setDesktopId(first.deviceId)
      await repository.setWorkspaceId('')
    }
    accessPanelOpen.value = !activeTrustedDevice.value
    if (!accessPanelOpen.value) startSync()
  } catch (error) {
    statusMessage.value = error instanceof Error ? error.message : String(error)
  }
}

function readManualGatewayUrl(): string {
  try {
    return globalThis.localStorage?.getItem(MANUAL_GATEWAY_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

let removeResumeListener: (() => void) | null = null

onMounted(async () => {
  await initialize()
  removeResumeListener = onMobileResume(() => { void restoreActiveConnection() })
})

onUnmounted(() => {
  stopAccountDiscovery()
  removeResumeListener?.()
  runtime.close()
  removeRepositoryListener()
  void syncEngine.close()
  void repository.close()
  connectionManager.close()
})
</script>

<style>
@import '@lamtools/ui/styles/variables.css';

.mobile-host {
  min-height: 100dvh;
  box-sizing: border-box;
  background: var(--theme-backdrop-background);
  color: var(--theme-backdrop-text);
}

.mobile-host-status {
  position: fixed;
  right: var(--space-3);
  bottom: var(--space-3);
  z-index: var(--z-toast);
  max-width: min(90vw, 360px);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  box-shadow: var(--shadow-md);
  font-size: 12px;
}

.mobile-access-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  box-sizing: border-box;
  padding: max(var(--space-4), env(safe-area-inset-top)) var(--space-4) max(var(--space-4), env(safe-area-inset-bottom));
  overflow: auto;
  background: color-mix(in srgb, var(--theme-backdrop-text) 8%, transparent);
  backdrop-filter: blur(4px);
}

@media (prefers-reduced-motion: reduce) {
  .mobile-access-overlay { backdrop-filter: none; }
}
@media (max-width: 640px) {
  .mobile-host { padding: 0; }
}
</style>
