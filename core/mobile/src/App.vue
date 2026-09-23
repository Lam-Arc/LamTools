<template>
  <main
    class="mobile-host"
    :class="{ 'mobile-host--left-drawer-open': leftDrawerOpen }"
  >
    <LamToolsApp
      ref="lamToolsAppRef"
      :runtime="runtime"
      :account-context="accountContext"
      :mobile-top-bar-hidden="topBarHidden"
      @left-drawer-change="leftDrawerOpen = $event"
      @mobile-mode-state="mobileModeState = $event"
      @sync-request="openSyncPanel()"
      @account-submit="authenticateCoreAccount"
      @account-logout="logoutAccount"
      @open-account="accessPanelOpen = true"
    />
    <MobileTopBar
      :hidden="topBarHidden"
      :syncing="isSyncing"
      :mode-options="mobileModeState.options"
      :active-mode-id="mobileModeState.activeId"
      :account-label="mobileAccountLabel"
      @open-sidebar="openLeftSidebar"
      @open-account="accessPanelOpen = true"
      @open-search="lamToolsAppRef?.openSearch()"
      @open-settings="lamToolsAppRef?.openSettings()"
      @select-mode="lamToolsAppRef?.selectAppModeByKey($event)"
    />
    <div v-if="accessPanelOpen" class="mobile-access-overlay">
      <PairingScreen
        :closable="true"
        :current-device="activeRuntimeMode === 'remote' ? activeTrustedDevice : null"
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
        @select-device="openDeviceSync"
        @forget-device="forgetDevice"
        @gateway-url-change="setManualGatewayUrl"
        @account-authenticate="authenticateAccount"
        @workspace-select="openWorkspaceSync"
        @account-logout="logoutAccount"
      />
    </div>
    <MobileSyncPanel
      v-if="syncPanelOpen"
      :devices="syncDevices"
      :projects="syncProjects"
      :initial-device-id="syncInitialDeviceId"
      :loading="syncProjectsLoading"
      :busy="syncActionBusy"
      :error="syncPanelError"
      @close="closeSyncPanel"
      @load-projects="loadSyncProjects"
      @confirm="confirmProjectSync"
    />
    <p v-if="statusMessage" class="mobile-host-status" role="status">{{ statusMessage }}</p>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { Capacitor } from '@capacitor/core'
import { createCoreProjectClient, createLamToolsRuntime, MobileTopBar, type CoreAppSnapshot, type CoreProject, type MobileControlAccountContext, type MobileControlAccountDevice, type MobileControlAccountPayload } from '@lamtools/ui'
import { CoreAppServerClient } from '@lamtools/ui/appServer'
import { mergeCoreHistorySnapshot } from '@lamtools/ui/appServer/store'
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
import { observeNativeWindowInsets } from './native/windowInsets'
import { loadOrCreateDeviceIdentity } from './pairing/DeviceIdentity'
import PairingScreen, {
  type AccountAuthRequest,
} from './pairing/PairingScreen.vue'
import { createLocalDatabase } from './storage/Database'
import { createLocalFirstProjectClient, createLocalRepository, type LocalState } from './storage'
import { createSwitchableProjectClient } from './storage/SwitchableProjectClient'
import { SwitchableTransport } from './connection/SwitchableTransport'
import { StandaloneTransport } from './standalone/StandaloneTransport'
import { loadLegacyMobileState } from './native/rustAgent'
import { createStandaloneProjectClient } from './standalone/StandaloneProjectClient'
import { SyncEngine } from './sync'
import MobileSyncPanel, { type MobileSyncDevice } from './sync/MobileSyncPanel.vue'

const MANUAL_GATEWAY_STORAGE_KEY = 'lamtools.mobile.manual-gateway-v1'
const SYNC_OFFLINE_DEVICES_STORAGE_KEY = 'lamtools.mobile.sync-offline-devices-v1'
const DEFAULT_SERVER_URL = 'wss://47.114.43.99.nip.io/v1/relay'

const statusMessage = ref('')
const lamToolsAppRef = ref<InstanceType<typeof LamToolsApp> | null>(null)
const mobileModeState = ref({
  label: '',
  title: '',
  canToggle: false,
  activeId: '',
  options: [] as Array<{ id: string; label: string }>,
})
const syncPanelOpen = ref(false)
const syncInitialDeviceId = ref('')
const syncProjects = ref<CoreProject[]>([])
const syncProjectsLoading = ref(false)
const syncActionBusy = ref(false)
const syncPanelError = ref('')
const syncOfflineDeviceIds = ref<Set<string>>(readSyncOfflineDeviceIds())
const syncProjectTargets = new Map<string, { projectId: string; workspaceId: string }>()
const accessPanelOpen = ref(false)
const leftDrawerOpen = ref(false)
const topBarHidden = computed(() => leftDrawerOpen.value || accessPanelOpen.value)
const activeTrustedDevice = ref<TrustedDevice | null>(null)
const trustedDevices = ref<TrustedDevice[]>([])
const accountClient = shallowRef<AccountClient | null>(null)
const accountWorkspaces = ref<AccountWorkspace[]>([])
const accountNodes = ref<AccountNode[]>([])
const accountLoading = ref(false)
const accountError = ref('')
const mobileAccountLabel = computed(() => accountClient.value?.session?.username || '登录 / 账号')
const manualGatewayUrl = ref(readManualGatewayUrl())
const activeWorkspaceId = ref('')
let accountOperationGeneration = 0
let workspaceSelectionGeneration = 0
let appDisposed = false
let accountOperationQueue: Promise<void> = Promise.resolve()
let workspaceSelectionQueue: Promise<void> = Promise.resolve()
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
const connectionManager = new ConnectionManager({
  relayEndpoint: import.meta.env.VITE_LAMTOOLS_RELAY_URL,
})
const syncConnectionManager = new ConnectionManager({
  relayEndpoint: import.meta.env.VITE_LAMTOOLS_RELAY_URL,
})
const syncRemoteProjectClient = createCoreProjectClient(syncConnectionManager.getTransport())
const localRepository = createLocalRepository(createLocalDatabase('lamtools-mobile-local'))
const remoteRepository = createLocalRepository()
const syncRepository = createLocalRepository(createLocalDatabase('lamtools-mobile-sync'))
const standaloneTransport = new StandaloneTransport(localRepository)
const transport = new SwitchableTransport(standaloneTransport)
const activeRuntimeMode = ref<'local' | 'remote'>('local')
const remoteProjectClient = createLocalFirstProjectClient(
  createCoreProjectClient(connectionManager.getTransport()),
  remoteRepository,
)
const localProjectClient = createStandaloneProjectClient(localRepository)
const projectClient = createSwitchableProjectClient(() => (
  activeRuntimeMode.value === 'remote' ? remoteProjectClient : localProjectClient
))
const activeRepository = () => activeRuntimeMode.value === 'remote' ? remoteRepository : localRepository
const syncDevices = computed<MobileSyncDevice[]>(() => {
  const accountDeviceMap = new Map<string, MobileSyncDevice>()
  for (const workspace of accountWorkspaces.value) {
    const hostKey = workspace.hostNodeId || workspace.workspaceId
    const id = `account-device:${hostKey}`
    const candidate: MobileSyncDevice = {
      id,
      label: workspace.host?.displayName || workspace.displayName,
      detail: '账号设备',
      online: workspace.online && !isSyncDeviceOffline(id),
    }
    const current = accountDeviceMap.get(hostKey)
    if (!current) accountDeviceMap.set(hostKey, candidate)
    else if (candidate.online) current.online = true
  }
  for (const [hostKey, device] of accountDeviceMap) {
    const count = accountWorkspaces.value.filter((workspace) => (workspace.hostNodeId || workspace.workspaceId) === hostKey).length
    device.detail = `${count} 个工作环境`
  }
  const accountDevices = [...accountDeviceMap.values()]
  const accountHostIds = new Set(accountWorkspaces.value.map((workspace) => workspace.hostNodeId))
  const directDevices = trustedDevices.value
    .filter((device) => !accountHostIds.has(device.deviceId))
    .map((device) => ({
      id: `device:${device.deviceId}`,
      label: device.name,
      detail: '已配对设备',
      online: !isSyncDeviceOffline(`device:${device.deviceId}`),
    }))
  return [...accountDevices, ...directDevices]
})
const runtime = createLamToolsRuntime({
  transport,
  platform: 'mobile',
  sessions: {
    listSessions: () => activeRepository().listSessions(),
  },
  projectClient,
  capabilities: {
    filePicker: true,
    notifications: Capacitor.isNativePlatform(),
    desktopWindow: false,
    files: createMobileFilePicker(),
    localProjects: computed(() => activeRuntimeMode.value === 'local'),
  },
})
const syncEngine = new SyncEngine({
  transport: connectionManager.getTransport(),
  repository: remoteRepository,
  requestRpc: (method, params, timeoutMs) => runtime.requestRpc(method, params, timeoutMs),
  onError: (message) => {
    if (isAppAlive()) statusMessage.value = `同步失败：${message}`
  },
})
const isSyncing = computed(() => syncEngine.state.value === 'syncing')
watch(syncEngine.state, (state) => {
  if (isAppAlive() && state === 'synced') statusMessage.value = ''
})
const refreshActiveRepository = () => {
  if (!isAppAlive()) return
  void Promise.all([
    runtime.workbench.refreshSessions(),
    Promise.resolve().then(() => window.dispatchEvent(new CustomEvent('lamtools:projects-synced'))),
  ])
}
const removeLocalRepositoryListener = localRepository.subscribe(() => {
  if (activeRuntimeMode.value === 'local') refreshActiveRepository()
})
const removeRemoteRepositoryListener = remoteRepository.subscribe(() => {
  if (activeRuntimeMode.value === 'remote') refreshActiveRepository()
})

function isAppAlive(): boolean {
  return !appDisposed
}

function isSelectionCurrent(generation: number): boolean {
  return isAppAlive() && workspaceSelectionGeneration === generation
}

function isAccountOperationCurrent(generation: number): boolean {
  return isAppAlive() && accountOperationGeneration === generation
}

function enqueueWorkspaceSelection(task: () => Promise<void>): Promise<void> {
  const next = workspaceSelectionQueue.then(task, task)
  workspaceSelectionQueue = next.catch(() => undefined)
  return next
}

function enqueueAccountOperation(task: () => Promise<void>): Promise<void> {
  const next = accountOperationQueue.then(task, task)
  accountOperationQueue = next.catch(() => undefined)
  return next
}

function openLeftSidebar(): void {
  // Closing the software keyboard before opening the fixed drawer prevents
  // Android's transient visual viewport from clipping the sidebar.
  const active = document.activeElement
  if (active instanceof HTMLElement) active.blur()
  window.requestAnimationFrame(() => lamToolsAppRef.value?.openLeftSidebar())
}

function closeAccessPanel(): void {
  accessPanelOpen.value = false
}

function openSyncPanel(deviceId = ''): void {
  syncInitialDeviceId.value = deviceId
  syncPanelError.value = ''
  syncPanelOpen.value = true
}

function openWorkspaceSync(workspaceId: string): void {
  accessPanelOpen.value = false
  const workspace = accountWorkspaces.value.find((item) => item.workspaceId === workspaceId)
  openSyncPanel(workspace ? `account-device:${workspace.hostNodeId || workspace.workspaceId}` : '')
}

function openDeviceSync(deviceId: string): void {
  accessPanelOpen.value = false
  openSyncPanel(`device:${deviceId}`)
}

function closeSyncPanel(): void {
  syncLoadGeneration += 1
  syncPanelOpen.value = false
  syncInitialDeviceId.value = ''
  syncProjects.value = []
  syncProjectsLoading.value = false
  syncPanelError.value = ''
  syncConnectionManager.close()
}

interface PreparedSyncDevice {
  online: boolean
  workspaceId: string
  account: AccountClient | null
  trustedDevice: TrustedDevice
}

async function prepareSyncDevice(
  deviceId: string,
  requestedWorkspaceId = '',
  expectedLoadGeneration?: number,
): Promise<PreparedSyncDevice> {
  assertSyncLoadCurrent(expectedLoadGeneration)
  if (deviceId.startsWith('account-device:') || deviceId.startsWith('workspace:')) {
    const legacyWorkspaceId = deviceId.startsWith('workspace:') ? deviceId.slice('workspace:'.length) : ''
    const hostNodeId = deviceId.startsWith('account-device:') ? deviceId.slice('account-device:'.length) : ''
    const workspace = accountWorkspaces.value.find((item) => (
      requestedWorkspaceId
        ? item.workspaceId === requestedWorkspaceId
        : legacyWorkspaceId
          ? item.workspaceId === legacyWorkspaceId
          : item.hostNodeId === hostNodeId
    ))
    const client = accountClient.value
    const host = workspace?.host
    if (!workspace || !client || !host?.publicKey) throw new Error('设备拒绝了您的请求')
    const workspaceId = workspace.workspaceId
    const device: TrustedDevice = {
      deviceId: workspace.hostNodeId,
      name: workspace.displayName || host.displayName,
      platform: host.platform,
      publicKey: host.publicKey,
      relayUrl: client.getRelayEndpoint(),
    }
    const session = client.session
    await syncRepository.setAccountScope(session?.serverId || '', session?.username || '')
    assertSyncLoadCurrent(expectedLoadGeneration)
    await syncRepository.setWorkspaceId(workspaceId)
    assertSyncLoadCurrent(expectedLoadGeneration)
    await syncRepository.setDesktopId(device.deviceId)
    assertSyncLoadCurrent(expectedLoadGeneration)
    const online = workspace.online && !isSyncDeviceOffline(`account-device:${workspace.hostNodeId || workspace.workspaceId}`)
    if (online) {
      await syncConnectionManager.setConnectionContext({ account: client, workspaceId, trustedDevice: device })
      assertSyncLoadCurrent(expectedLoadGeneration)
    }
    return { online, workspaceId, account: client, trustedDevice: device }
  }
  const trustedId = deviceId.slice('device:'.length)
  const device = trustedDevices.value.find((item) => item.deviceId === trustedId)
  if (!device) throw new Error('设备拒绝了您的请求')
  await syncRepository.setAccountScope('', '')
  assertSyncLoadCurrent(expectedLoadGeneration)
  await syncRepository.setWorkspaceId('')
  assertSyncLoadCurrent(expectedLoadGeneration)
  await syncRepository.setDesktopId(device.deviceId)
  assertSyncLoadCurrent(expectedLoadGeneration)
  const online = !isSyncDeviceOffline(deviceId)
  await syncConnectionManager.setConnectionContext({ account: null, workspaceId: '', trustedDevice: device })
  assertSyncLoadCurrent(expectedLoadGeneration)
  return { online, workspaceId: '', account: null, trustedDevice: device }
}

let syncLoadGeneration = 0

class SyncLoadCancelledError extends Error {}

function assertSyncLoadCurrent(expectedGeneration?: number): void {
  if (expectedGeneration !== undefined && expectedGeneration !== syncLoadGeneration) {
    throw new SyncLoadCancelledError('同步项目读取已取消')
  }
}

async function loadSyncProjects(deviceId: string): Promise<void> {
  const generation = ++syncLoadGeneration
  syncProjectsLoading.value = true
  syncPanelError.value = ''
  syncProjects.value = []
  syncProjectTargets.clear()
  try {
    const workspaces = deviceId.startsWith('account-device:')
      ? accountWorkspaces.value.filter((workspace) => (
        (workspace.hostNodeId || workspace.workspaceId) === deviceId.slice('account-device:'.length)
      ))
      : [null]
    if (!workspaces.length) throw new Error('设备拒绝了您的请求')
    const combined: CoreProject[] = []
    let liveSucceeded = false
    let lastLiveError: unknown = null
    for (const workspace of workspaces) {
      if (generation !== syncLoadGeneration) return
      const prepared = await prepareSyncDevice(deviceId, workspace?.workspaceId || '', generation)
      if (generation !== syncLoadGeneration) return
      const cached = await syncRepository.listProjects()
      if (generation !== syncLoadGeneration) return
      let projects = cached.map(localProjectToCoreProject)
      if (prepared.online || deviceId.startsWith('device:')) {
        try {
          if (generation !== syncLoadGeneration) return
          projects = await syncRemoteProjectClient.list()
          if (generation !== syncLoadGeneration) return
          liveSucceeded = true
        } catch (error) {
          if (generation !== syncLoadGeneration) return
          lastLiveError = error
        }
      }
      const groupLabel = workspace?.displayName || prepared.trustedDevice.name
      for (const project of projects) {
        const selectionId = `${encodeURIComponent(prepared.workspaceId || prepared.trustedDevice.deviceId)}:${encodeURIComponent(project.id)}`
        syncProjectTargets.set(selectionId, { projectId: project.id, workspaceId: prepared.workspaceId })
        combined.push({
          ...project,
          id: selectionId,
          workRoot: `${groupLabel} · ${project.workRoot || ''}`,
        })
      }
      if (generation !== syncLoadGeneration) return
    }
    syncProjects.value = combined
    if (liveSucceeded) setSyncDeviceOffline(deviceId, false)
    else if (lastLiveError) {
      setSyncDeviceOffline(deviceId, true)
      if (!combined.length) throw new Error('设备已下线，且没有可导入的项目缓存', { cause: lastLiveError })
    }
  } catch (error) {
    if (generation !== syncLoadGeneration || error instanceof SyncLoadCancelledError) return
    if (generation === syncLoadGeneration) {
      syncPanelError.value = error instanceof Error ? error.message : String(error)
    }
  } finally {
    if (generation === syncLoadGeneration) syncProjectsLoading.value = false
  }
}

async function syncRemoteSnapshot(projectId: string): Promise<void> {
  const client = new CoreAppServerClient({
    transport: syncConnectionManager.getTransport(),
    clientInfo: { name: 'lamtools_mobile_import', title: 'LamTools Mobile Import', version: '0.1.1' },
  })
  try {
    await client.connect()
    let cursor: number | null = null
    const seenSyncCursors = new Set<string>()
    while (true) {
      const requestCursorKey = cursor == null ? 'initial' : String(cursor)
      if (seenSyncCursors.has(requestCursorKey)) throw new Error('同步游标重复，已停止导入')
      seenSyncCursors.add(requestCursorKey)
      const result = await client.request('sync.start', { cursor, limit: 500 }, 60_000)
      if (result.ok === false) throw new Error(String(result.error || '同步失败'))
      if (result.mode === 'snapshot') await syncRepository.applySyncSnapshot(result)
      else if (Array.isArray(result.changes)) {
        for (const change of result.changes) {
          if (change && typeof change === 'object') await syncRepository.applySyncChange(change as any)
        }
      }
      const nextCursor = Number(result.cursor)
      cursor = Number.isSafeInteger(nextCursor) && nextCursor >= 0 ? nextCursor : syncRepository.state.value.cursor
      if (result.has_more === true && cursor == null) throw new Error('同步响应缺少有效游标')
      if (result.has_more !== true) break
    }

    const projectThreads = Object.values(syncRepository.state.value.threads)
      .filter((thread) => !thread.deleted && thread.projectId === projectId)
    for (const thread of projectThreads) {
      const resumed = await client.request('thread/resume', {
        thread_id: thread.id,
        last_seen_seq: 0,
        turn_limit: 100,
      }, 60_000)
      if (!resumed.snapshot || typeof resumed.snapshot !== 'object') {
        throw new Error(`无法读取会话：${thread.title}`)
      }
      let snapshot = resumed.snapshot as unknown as CoreAppSnapshot
      const seenCursors = new Set<string>()
      while (snapshot.history_page?.has_more === true) {
        const beforeItemId = String(snapshot.history_page.next_before_item_id || '')
        const beforeSeq = Number(snapshot.history_page.next_before_seq || 0)
        const cursorKey = `${beforeItemId}:${beforeSeq}`
        if (!beforeItemId && beforeSeq <= 0) throw new Error(`会话历史缺少有效游标：${thread.title}`)
        if (seenCursors.has(cursorKey)) throw new Error(`会话历史游标重复：${thread.title}`)
        seenCursors.add(cursorKey)
        const history = await client.request('thread.history', {
          thread_id: thread.id,
          before_item_id: beforeItemId || undefined,
          before_seq: beforeSeq || undefined,
          turn_limit: 100,
        }, 60_000)
        if (!history.snapshot_page || typeof history.snapshot_page !== 'object') throw new Error(`无法继续读取会话：${thread.title}`)
        snapshot = mergeCoreHistorySnapshot(snapshot, history.snapshot_page as unknown as CoreAppSnapshot)
      }
      await syncRepository.saveLocalSnapshot(snapshot)
    }
  } finally {
    client.close()
  }
}

async function confirmProjectSync(payload: { deviceId: string; projectId: string; mode: 'remote' | 'import' }): Promise<void> {
  const previousRemote = activeRuntimeMode.value === 'remote' && activeTrustedDevice.value
    ? {
        workspaceId: activeWorkspaceId.value,
        account: activeWorkspaceId.value ? accountClient.value : null,
        trustedDevice: activeTrustedDevice.value,
      }
    : null
  syncActionBusy.value = true
  syncPanelError.value = ''
  try {
    const target = syncProjectTargets.get(payload.projectId)
    const projectId = target?.projectId || payload.projectId
    const prepared = await prepareSyncDevice(payload.deviceId, target?.workspaceId || '')
    if (payload.mode === 'remote') {
      if (!prepared.online) throw new Error('设备已下线，无法远控')
      await syncEngine.close()
      runtime.workbench.disconnect()
      if (prepared.account && prepared.workspaceId) {
        await prepared.account.selectWorkspace(prepared.workspaceId)
      }
      await connectionManager.setConnectionContext({
        account: prepared.account,
        workspaceId: prepared.workspaceId,
        trustedDevice: prepared.trustedDevice,
      })
      activeWorkspaceId.value = prepared.workspaceId
      activeTrustedDevice.value = prepared.trustedDevice
      const session = prepared.account?.session
      await remoteRepository.setAccountScope(session?.serverId || '', session?.username || '')
      await remoteRepository.setWorkspaceId(prepared.workspaceId)
      await remoteRepository.setDesktopId(prepared.trustedDevice.deviceId)
      syncConnectionManager.close()
      await transport.use(connectionManager.getTransport())
      activeRuntimeMode.value = 'remote'
      await syncEngine.start()
      if (syncEngine.state.value !== 'synced') throw new Error(syncEngine.lastError.value || '设备已下线，无法远控')
      await lamToolsAppRef.value?.refreshPluginModes()
      await runtime.workbench.refreshSessions()
      window.dispatchEvent(new CustomEvent('lamtools:projects-synced'))
      if (!remoteRepository.state.value.projects[projectId]) throw new Error('未能从设备同步所选项目')
      await lamToolsAppRef.value?.openProject(projectId)
      setSyncDeviceOffline(payload.deviceId, false)
      closeSyncPanel()
      statusMessage.value = '已进入远控模式'
      return
    }

    if (prepared.online) await syncRemoteSnapshot(projectId)
    const sourceProject = syncRepository.state.value.projects[projectId]
    if (!sourceProject || sourceProject.deleted) throw new Error('暂无可导入的项目缓存')
    const threads = Object.values(syncRepository.state.value.threads)
      .filter((thread) => !thread.deleted && thread.projectId === projectId)
    const snapshots = threads.flatMap((thread) => {
      const snapshot = syncRepository.state.value.snapshots[thread.id]
      return snapshot ? [snapshot] : []
    })
    const imported = await localRepository.importLocalProject(sourceProject, threads, snapshots)
    if (activeRuntimeMode.value !== 'local') {
      await syncEngine.close()
      runtime.workbench.disconnect()
      await transport.use(standaloneTransport)
      activeRuntimeMode.value = 'local'
      await lamToolsAppRef.value?.refreshPluginModes()
    }
    await runtime.workbench.refreshSessions()
    window.dispatchEvent(new CustomEvent('lamtools:projects-synced'))
    await lamToolsAppRef.value?.openProject(imported.id)
    closeSyncPanel()
    statusMessage.value = `已导入项目：${sourceProject.name}`
  } catch (error) {
    if (payload.mode === 'remote') {
      setSyncDeviceOffline(payload.deviceId, true)
      if (activeRuntimeMode.value === 'remote') {
        const restored = previousRemote ? await restoreRemoteSession(previousRemote) : false
        if (!restored) {
          await syncEngine.close()
          runtime.workbench.disconnect()
          await transport.use(standaloneTransport)
          activeRuntimeMode.value = 'local'
          await lamToolsAppRef.value?.refreshPluginModes()
          await runtime.workbench.refreshSessions()
        }
      }
    }
    syncPanelError.value = error instanceof Error ? error.message : String(error)
  } finally {
    syncActionBusy.value = false
  }
}

async function restoreRemoteSession(previous: Omit<PreparedSyncDevice, 'online'>): Promise<boolean> {
  try {
    await syncEngine.close()
    runtime.workbench.disconnect()
    if (previous.account && previous.workspaceId) await previous.account.selectWorkspace(previous.workspaceId)
    await connectionManager.setConnectionContext({
      account: previous.account,
      workspaceId: previous.workspaceId,
      trustedDevice: previous.trustedDevice,
    })
    const session = previous.account?.session
    await remoteRepository.setAccountScope(session?.serverId || '', session?.username || '')
    await remoteRepository.setWorkspaceId(previous.workspaceId)
    await remoteRepository.setDesktopId(previous.trustedDevice.deviceId)
    activeWorkspaceId.value = previous.workspaceId
    activeTrustedDevice.value = previous.trustedDevice
    await transport.use(connectionManager.getTransport())
    activeRuntimeMode.value = 'remote'
    await syncEngine.start()
    if (syncEngine.state.value !== 'synced') return false
    await lamToolsAppRef.value?.refreshPluginModes()
    await runtime.workbench.refreshSessions()
    return true
  } catch {
    return false
  }
}

async function handlePaired(device: TrustedDevice): Promise<void> {
  const selectionGeneration = ++workspaceSelectionGeneration
  await enqueueWorkspaceSelection(async () => {
    if (!isSelectionCurrent(selectionGeneration)) return
    activeWorkspaceId.value = ''
    trustedDevices.value = [
      device,
      ...trustedDevices.value.filter((item) => item.deviceId !== device.deviceId),
    ]
    activeTrustedDevice.value = device
    accessPanelOpen.value = false
    accountError.value = ''
    statusMessage.value = ''
  })
}

async function forgetDevice(deviceId: string): Promise<void> {
  try {
    await forgetTrustedDevice(deviceId)
    if (!isAppAlive()) return
    trustedDevices.value = trustedDevices.value.filter((device) => device.deviceId !== deviceId)
    if (activeTrustedDevice.value?.deviceId === deviceId && !activeWorkspaceId.value) {
      activeTrustedDevice.value = null
      connectionManager.setTrustedDevice(null)
      if (activeRuntimeMode.value === 'remote') {
        await syncEngine.close()
        runtime.workbench.disconnect()
        await transport.use(standaloneTransport)
        activeRuntimeMode.value = 'local'
        await lamToolsAppRef.value?.refreshPluginModes()
        await runtime.workbench.refreshSessions()
      }
    }
    statusMessage.value = '已忘记这台电脑'
  } catch (error) {
    if (isAppAlive()) statusMessage.value = error instanceof Error ? error.message : String(error)
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
  const operationGeneration = ++accountOperationGeneration
  ++workspaceSelectionGeneration
  return await enqueueAccountOperation(async () => {
    if (!isAccountOperationCurrent(operationGeneration)) return
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
      if (!isAccountOperationCurrent(operationGeneration)) {
        // Account operations are serialized, so removing this stale session
        // cannot erase credentials from the newer operation queued behind it.
        await client.logout()
        return
      }
      accountClient.value = client
      connectionManager.setAccount(client)
      await loadWorkspaces(client, operationGeneration)
      if (!isAccountOperationCurrent(operationGeneration) || client !== accountClient.value) return
      startAccountDiscovery()
      statusMessage.value = `已登录 ${client.session?.username || request.username}`
    } catch (error) {
      if (isAccountOperationCurrent(operationGeneration)) {
        accountError.value = error instanceof Error ? error.message : String(error)
      }
    } finally {
      if (isAccountOperationCurrent(operationGeneration)) accountLoading.value = false
    }
  })
}

function authenticateCoreAccount(payload: MobileControlAccountPayload): void {
  void authenticateAccount({
    mode: payload.mode,
    serverUrl: payload.baseUrl,
    username: payload.username,
    password: payload.password,
  })
}

async function loadWorkspaces(client: AccountClient, operationGeneration?: number): Promise<void> {
  const [workspaces, nodes] = await Promise.all([
    client.listWorkspaces(),
    client.listNodes(),
  ])
  // A logout or a newer login may have replaced the account while the
  // requests were in flight. Never repopulate the new account with stale
  // workspace data or activate an old account's host.
  if (!isAppAlive()
    || client !== accountClient.value
    || (operationGeneration !== undefined && operationGeneration !== accountOperationGeneration)) return
  accountWorkspaces.value = workspaces
  accountNodes.value = nodes
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
        if (isAppAlive()) accountError.value = error instanceof Error ? error.message : String(error)
      })
      .finally(() => { accountDiscoveryRunning = false })
  }, 3_000)
}

function stopAccountDiscovery(): void {
  if (accountDiscoveryTimer) clearInterval(accountDiscoveryTimer)
  accountDiscoveryTimer = null
  accountDiscoveryRunning = false
}

async function logoutAccount(): Promise<void> {
  const operationGeneration = ++accountOperationGeneration
  workspaceSelectionGeneration += 1
  stopAccountDiscovery()
  const client = accountClient.value
  accountLoading.value = false
  accountClient.value = null
  accountWorkspaces.value = []
  accountNodes.value = []
  activeWorkspaceId.value = ''
  connectionManager.setAccount(null)
  connectionManager.setWorkspace('')
  return await enqueueAccountOperation(async () => {
    // Always finish the requested sign-out before a newer queued login starts.
    // Skipping this cleanup would leave the old session persisted when the
    // replacement login later fails.
    if (activeRuntimeMode.value === 'remote') {
      await syncEngine.close()
      runtime.workbench.disconnect()
      await transport.use(standaloneTransport)
      activeRuntimeMode.value = 'local'
      await lamToolsAppRef.value?.refreshPluginModes()
      await runtime.workbench.refreshSessions()
    }
    await remoteRepository.setAccountScope('', '')
    await remoteRepository.setWorkspaceId('')
    await syncRepository.setAccountScope('', '')
    await syncRepository.setWorkspaceId('')
    if (client) await client.logout()
    if (!isAccountOperationCurrent(operationGeneration)) return
    if (!isAppAlive()) return
    if (activeTrustedDevice.value && !activeTrustedDevice.value.accessToken) {
      activeTrustedDevice.value = null
      connectionManager.setTrustedDevice(null)
    }
    if (!isAppAlive()) return
    statusMessage.value = '已退出服务器账号'
  })
}

async function restoreActiveConnection(): Promise<void> {
  if (!isAppAlive() || accessPanelOpen.value || activeRuntimeMode.value !== 'remote') return
  connectionManager.prepareForResume()
  try {
    const activeSessionId = runtime.workbench.activeSessionId.value
    if (activeSessionId) await runtime.workbench.connect(activeSessionId)
    if (!isAppAlive()) return
    await runtime.workbench.refreshSessions()
    if (!isAppAlive()) return
  } catch (error) {
    if (isAppAlive()) statusMessage.value = error instanceof Error ? error.message : String(error)
  }
}

async function initialize(): Promise<void> {
  try {
    await localRepository.init()
    if (!isAppAlive()) return
    const legacyState = await loadLegacyMobileState<LocalState>()
    if (legacyState) await localRepository.importLegacyState(legacyState)
    if (!isAppAlive()) return
    await remoteRepository.init()
    if (!isAppAlive()) return
    await syncRepository.init()
    if (!isAppAlive()) return
    await standaloneTransport.connect()
    if (!isAppAlive()) return
    await runtime.workbench.refreshSessions()
    if (!isAppAlive()) return
    const loadedIdentity = await loadOrCreateDeviceIdentity()
    if (!isAppAlive()) return
    connectionManager.setDeviceId(loadedIdentity.deviceId)
    syncConnectionManager.setDeviceId(loadedIdentity.deviceId)
    await connectionManager.startNetworkMonitoring()
    if (!isAppAlive()) return

    const restoreGeneration = accountOperationGeneration
    const restoredAccount = await loadStoredAccount()
    if (!isAppAlive()) return
    if (restoredAccount && restoreGeneration === accountOperationGeneration) {
      accountClient.value = restoredAccount
      connectionManager.setAccount(restoredAccount)
      try {
        await loadWorkspaces(restoredAccount, restoreGeneration)
        if (!isAppAlive()) return
        if (restoreGeneration === accountOperationGeneration && restoredAccount === accountClient.value) {
          startAccountDiscovery()
        }
      } catch (error) {
        if (isAppAlive() && restoreGeneration === accountOperationGeneration) {
          accountError.value = error instanceof Error ? error.message : String(error)
        }
      }
    }

    if (!isAppAlive()) return
    trustedDevices.value = await listTrustedDevices()
    if (!isAppAlive()) return
    if (!activeTrustedDevice.value && trustedDevices.value[0]) {
      const first = trustedDevices.value[0]
      activeTrustedDevice.value = first
      connectionManager.setWorkspace('')
      connectionManager.setTrustedDevice(first)
      await remoteRepository.setDesktopId(first.deviceId)
      if (!isAppAlive()) return
      await remoteRepository.setWorkspaceId('')
      if (!isAppAlive()) return
    }
    accessPanelOpen.value = false
  } catch (error) {
    if (isAppAlive()) statusMessage.value = error instanceof Error ? error.message : String(error)
  }
}

function readManualGatewayUrl(): string {
  try {
    return globalThis.localStorage?.getItem(MANUAL_GATEWAY_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

function readSyncOfflineDeviceIds(): Set<string> {
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(SYNC_OFFLINE_DEVICES_STORAGE_KEY) || '[]')
    return new Set(Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [])
  } catch {
    return new Set()
  }
}

function setSyncDeviceOffline(deviceId: string, offline: boolean): void {
  const next = new Set(syncOfflineDeviceIds.value)
  const storageKey = syncOfflineStorageKey(deviceId)
  if (offline) next.add(storageKey)
  else next.delete(storageKey)
  syncOfflineDeviceIds.value = next
  try {
    globalThis.localStorage?.setItem(SYNC_OFFLINE_DEVICES_STORAGE_KEY, JSON.stringify([...next]))
  } catch {
    // Storage denial must not prevent the current session from updating.
  }
}

function isSyncDeviceOffline(deviceId: string): boolean {
  return syncOfflineDeviceIds.value.has(syncOfflineStorageKey(deviceId))
}

function syncOfflineStorageKey(deviceId: string): string {
  if (deviceId.startsWith('account-device:') || deviceId.startsWith('workspace:')) {
    const session = accountClient.value?.session
    const server = encodeURIComponent(session?.serverId || 'anonymous')
    const account = encodeURIComponent((session?.username || 'anonymous').trim().toLowerCase())
    return `account:${server}:${account}:${deviceId}`
  }
  return `paired:${deviceId}`
}

function localProjectToCoreProject(
  project: Awaited<ReturnType<typeof syncRepository.listProjects>>[number],
): CoreProject {
  return {
    id: project.id,
    name: project.name,
    workRoot: project.workRoot || project.path,
    iconKey: (project.iconKey || 'folder') as CoreProject['iconKey'],
    colorKey: (project.colorKey || 'gray') as CoreProject['colorKey'],
    createdAt: project.createdAt,
    updatedAt: project.updatedAt,
  }
}

let removeResumeListener: (() => void) | null = null
let removeWindowInsetsListener: (() => void) | null = null

function syncNativeWindowInsets(insets: { top: number }): void {
  // The Android bridge reports CSS pixels. Keeping the value on :root lets
  // the shared MobileTopBar inherit it without coupling the UI package to
  // Tauri or Android.
  const top = Number.isFinite(insets.top) ? Math.max(0, insets.top) : 0
  document.documentElement.style.setProperty('--native-safe-area-top', `${top}px`)
}

onMounted(async () => {
  removeWindowInsetsListener = observeNativeWindowInsets(syncNativeWindowInsets)
  await initialize()
  if (!isAppAlive()) return
  removeResumeListener = onMobileResume(() => { void restoreActiveConnection() })
})

onUnmounted(() => {
  appDisposed = true
  accountOperationGeneration += 1
  workspaceSelectionGeneration += 1
  stopAccountDiscovery()
  removeResumeListener?.()
  removeWindowInsetsListener?.()
  document.documentElement.style.removeProperty('--native-safe-area-top')
  runtime.close()
  removeLocalRepositoryListener()
  removeRemoteRepositoryListener()
  connectionManager.close()
  syncConnectionManager.close()
  void (async () => {
    await syncEngine.close()
    await localRepository.close()
    await remoteRepository.close()
    await syncRepository.close()
  })()
})
</script>

<style>
@import '@lamtools/ui/styles/variables.css';

.mobile-host {
  --mobile-header-offset: max(var(--native-safe-area-top, 0px), env(safe-area-inset-top, 0px));
  --titlebar-offset: var(--mobile-header-offset);
  min-height: 100dvh;
  box-sizing: border-box;
  background: var(--theme-main-background);
  color: var(--theme-main-text);
}

.mobile-host::before {
  content: '';
  position: fixed;
  inset: 0 0 auto;
  z-index: var(--z-main-surface);
  height: var(--mobile-header-offset);
  background: var(--theme-main-background);
  pointer-events: none;
}

.mobile-host--left-drawer-open::before {
  background: var(--theme-backdrop-background);
}

@media (max-width: 640px) {
  .mobile-host .workspace-main {
    padding-top: calc(var(--space-6) + var(--space-1));
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }
  .mobile-host .workspace-shell--full-bleed .workspace-main { padding-top: 0; }
  .mobile-host .drawer-left { padding-top: var(--space-4); }
  .mobile-host .drawer-left {
    top: 0;
    height: 100dvh;
    padding-top: calc(var(--mobile-header-offset) + var(--space-4));
  }
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
  padding: max(var(--space-4), var(--mobile-header-offset, env(safe-area-inset-top, 0px))) var(--space-4) max(var(--space-4), env(safe-area-inset-bottom, 0px));
  overflow: auto;
  background: color-mix(in srgb, var(--theme-backdrop-text) 8%, transparent);
  backdrop-filter: blur(4px);
}

@media (prefers-reduced-motion: reduce) {
  .mobile-access-overlay { backdrop-filter: none; }
}
@media (max-width: 640px) { .mobile-host { padding: 0; } }
</style>
