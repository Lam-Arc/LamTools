<script setup lang="ts">
/**
 * CoreWorkbenchView -- LamImager Core UI
 *
 * Uses @lamtools/ui components with slot-driven layout.
 * WorkspaceShell receives ARTIST_SLOT_SET for slot resolution.
 * Product-specific logic (adapter, sessionGroups, usage, drawer info) stays here;
 * all shared state/control is delegated to the Core controller.
 */
import { computed, onMounted, ref } from 'vue'
import {
  WorkspaceShell,
  SessionSidebar,
  ChatThread,
  ComposerBar,
  RuntimePanel,
  useCoreWorkbenchController,
  useMemberSlots,
} from '@lamtools/ui'
import type {
  CoreSessionGroup,
  ProductAdapter,
  CoreWorkbenchApi,
} from '@lamtools/ui'
import {
  listCoreSessions,
  createCoreSession,
  getCoreMessages,
  createCoreMessage,
  getCoreEvents,
  listCoreProviders,
  getCoreUsageTotal,
} from '@/api/core'
import { ARTIST_SLOT_SET, validateArtistSlotSet } from '@/memberSlots'

const slotErrors = validateArtistSlotSet()
if (slotErrors.length > 0) {
  console.warn('[Artist] Slot validation errors:', slotErrors)
}

useMemberSlots(ARTIST_SLOT_SET)

const imagerAdapter: ProductAdapter = {
  id: 'imager',
  displayName: 'LamImager',
  version: '0.1.0',
  supportedFeatures: ['chat', 'runtime-events', 'image-generation'],
}

const sessionGroups = computed<CoreSessionGroup[]>(() => [
  {
    id: 'imager-sessions',
    label: 'Imager sessions',
    description: 'All Imager sessions',
  },
])

const usageTotal = ref<number | null>(null)
const usageCurrency = ref('CNY')

const api: CoreWorkbenchApi = {
  listSessions: listCoreSessions,
  createSession: createCoreSession,
  getMessages: getCoreMessages,
  createMessage: createCoreMessage,
  getEvents: getCoreEvents,
  listProviders: async () => (await listCoreProviders()).data,
}

const {
  sessions,
  activeSessionId,
  messages,
  events,
  composerText,
  loading,
  providerCount,
  stepGroups,
  selectSession,
  newSession,
  sendMessage,
  loadInitialData,
} = useCoreWorkbenchController({
  api,
  onMountedExtra: async () => {
    try {
      const usageRes = await getCoreUsageTotal()
      if (usageRes.data) {
        usageTotal.value = usageRes.data.total_cost
        usageCurrency.value = usageRes.data.currency
      }
    } catch (err) {
      console.error('Failed to load usage:', err)
    }
  },
})

const activeSession = computed(() =>
  sessions.value.find(s => s.id === activeSessionId.value) ?? null,
)

const usageLabel = computed(() =>
  usageTotal.value !== null
    ? `${usageTotal.value.toFixed(2)} ${usageCurrency.value}`
    : '-',
)

onMounted(() => {
  loadInitialData()
})
</script>

<template>
  <WorkspaceShell :member-slot-set="ARTIST_SLOT_SET">
    <template #sidebar-header>
      <div class="ltw-sidebar-header">
        <span class="ltw-sidebar-title">{{ imagerAdapter.displayName }} Core</span>
        <span v-if="providerCount > 0" class="ltw-sidebar-subtitle">
          {{ providerCount }} provider(s)
        </span>
      </div>
    </template>

    <template #sidebar>
      <SessionSidebar
        :sessions="sessions"
        :active-id="activeSessionId ?? undefined"
        :groups="sessionGroups"
        @select="selectSession"
      />
    </template>

    <template #sidebar-footer>
      <button
        class="ltw-new-session-btn"
        @click="newSession"
      >
        + New Session
      </button>
    </template>

    <template #chat>
      <div v-if="!activeSessionId" class="ltw-empty-state">
        Select or create a session to begin.
      </div>
      <template v-else>
        <ChatThread :messages="messages" />
        <ComposerBar
          v-model="composerText"
          :disabled="loading"
          placeholder="Send a message..."
          @submit="sendMessage"
        >
          <template #toolbar-custom>
            <span v-if="providerCount > 0" class="ltw-toolbar-status">
              {{ providerCount }} provider(s)
            </span>
            <span v-if="usageTotal !== null" class="ltw-toolbar-status">
              {{ usageLabel }}
            </span>
          </template>
        </ComposerBar>
      </template>
    </template>

    <template #drawer-right>
      <RuntimePanel
        :events="events"
        :step-groups="stepGroups"
      />
      <div v-if="activeSession" class="core-drawer-info">
        <div class="core-drawer-info__row">
          <span class="core-drawer-info__label">Status</span>
          <span class="core-drawer-info__value">{{ activeSession.status ?? '-' }}</span>
        </div>
        <div class="core-drawer-info__row">
          <span class="core-drawer-info__label">Messages</span>
          <span class="core-drawer-info__value">{{ messages.length }}</span>
        </div>
      </div>
    </template>
  </WorkspaceShell>
</template>

<style scoped>
.core-drawer-info {
  padding: 12px 0;
  border-top: 1px solid var(--color-border);
}

.core-drawer-info__row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 13px;
}

.core-drawer-info__label {
  color: var(--color-text-secondary);
}

.core-drawer-info__value {
  color: var(--color-text);
  font-weight: 600;
}
</style>
