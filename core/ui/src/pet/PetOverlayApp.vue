<template>
  <main class="pet-overlay">
    <header>
      <div>
        <p class="eyebrow">LAMTOOLS PET</p>
        <h1>{{ stateLabel }}</h1>
      </div>
      <button class="close" type="button" aria-label="关闭" @click="close">×</button>
    </header>

    <section v-if="connectionState !== 'open'" class="card connection-card">
      <p>桌宠面板暂时无法连接 Core，审批和设置不会丢失。</p>
      <button class="primary" type="button" @click="retryNow">重试连接</button>
    </section>

    <section v-if="overview.pending_interactions.length" class="section">
      <div v-if="activeInteraction" class="card waiting-card">
        <div class="queue-count" v-if="overview.pending_interactions.length > 1">当前处理第 1 项，共 {{ overview.pending_interactions.length }} 项</div>
        <template v-if="activeInteraction">
        <div v-for="item in [activeInteraction]" :key="item.id">
        <span class="card-kind">{{ item.type === 'approval' ? '需要审批' : '需要回答' }}</span>
        <strong>{{ item.title }}</strong>
        <p>{{ item.message }}</p>
        <div class="actions" v-if="item.type === 'approval'">
          <button class="primary" type="button" :disabled="responding" @click="respond(item, 'approve_once')">允许</button>
          <button type="button" :disabled="responding" @click="respond(item, 'deny')">拒绝</button>
          <button type="button" :disabled="responding" @click="showGuidance = true">指导</button>
        </div>
        <div v-if="item.type === 'approval' && showGuidance" class="guidance-box">
          <textarea
            v-model="guidanceDraft"
            rows="3"
            placeholder="告诉 Agent 应该怎么做"
            :disabled="responding"
            @keydown.ctrl.enter.prevent="submitGuidance(item)"
          />
          <button class="primary" type="button" :disabled="responding || !guidanceDraft.trim()" @click="submitGuidance(item)">发送指导</button>
        </div>
        <div class="actions" v-else-if="item.type !== 'approval'">
          <button v-for="option in item.options" :key="option" class="primary" type="button" :disabled="responding" @click="respond(item, 'other_guidance', option)">{{ option }}</button>
        </div>
        <div v-if="item.type !== 'approval'" class="guidance-box">
          <textarea
            v-model="guidanceDraft"
            rows="3"
            placeholder="输入回答"
            :disabled="responding"
            @keydown.ctrl.enter.prevent="submitGuidance(item)"
          />
          <button class="primary" type="button" :disabled="responding || !guidanceDraft.trim()" @click="submitGuidance(item)">提交回答</button>
        </div>
        </div>
        </template>
      </div>
    </section>

    <section v-if="overview.active_errors.length" class="section">
      <div v-for="(error, index) in overview.active_errors" :key="String(error.thread_id || index)" class="card error-card">
        <span class="card-kind">执行错误</span>
        <p>{{ String(error.message || error.error || '任务执行失败') }}</p>
        <button v-if="error.thread_id" type="button" @click="openSession(String(error.thread_id))">在主窗口查看</button>
      </div>
    </section>

    <section class="settings">
      <label><span>宠物</span><select v-model="settings.selected_pet" @change="saveSettings"><option value="default-cat">小猫</option><option value="default-fox">小狐</option><option value="default-robot">小机器人</option><option v-for="pack in customPacks" :key="pack.id" :value="pack.id" :disabled="!pack.valid">{{ pack.name }}{{ pack.valid ? '' : '（无效）' }}</option></select></label>
      <label><span>透明度</span><input v-model.number="settings.opacity" type="range" min="0.2" max="1" step="0.05" @change="saveSettings"></label>
      <label><span>大小</span><input v-model.number="settings.scale" type="range" min="0.5" max="2" step="0.1" @change="saveSettings"></label>
      <label class="toggle"><input v-model="settings.enabled" type="checkbox" @change="toggleEnabled"><span>显示桌宠</span></label>
    </section>

    <button class="main-button" type="button" @click="focusMain">打开 LamTools 主窗口</button>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { emit, listen, type UnlistenFn } from '@tauri-apps/api/event'
import { createPetClient, defaultPetSettings, normalizeOverview, type PetInteraction, type PetOverview, type PetPack, type PetSettings } from './petClient'

const overview = ref<PetOverview>(normalizeOverview(null))
const settings = reactive<PetSettings>(defaultPetSettings(null))
const packs = ref<PetPack[]>([])
type PetClient = Awaited<ReturnType<typeof createPetClient>>['client']
let client: PetClient | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let mounted = false
let unlistenSettings: UnlistenFn | null = null
let unlistenVisibility: UnlistenFn | null = null
const stateLabel = ref('正在连接…')
const connectionState = ref<'connecting' | 'open' | 'closed' | 'error'>('connecting')
const customPacks = computed(() => packs.value.filter(pack => !pack.id.startsWith('default-')))
const activeInteraction = computed(() => overview.value.pending_interactions[0] || null)
const responding = ref(false)
const showGuidance = ref(false)
const guidanceDraft = ref('')

watch(() => activeInteraction.value?.id, () => {
  showGuidance.value = false
  guidanceDraft.value = ''
})

async function connect() {
  client?.close()
  client = null
  connectionState.value = 'connecting'
  stateLabel.value = '正在准备连接…'
  try {
    const created = await createPetClient(value => {
      overview.value = value
      stateLabel.value = value.global_state === 'waiting' ? '有事项需要你处理' : value.global_state === 'error' ? '有任务发生错误' : value.global_state === 'running' ? '任务运行中' : '一切平稳'
    }, state => {
      connectionState.value = state
      if (state === 'error' || state === 'closed') {
        stateLabel.value = '暂时无法连接 Core'
        scheduleReconnect()
      }
    }, 'lamtools-pet-overlay')
    stateLabel.value = '正在连接 Core…'
    client = created.client
    await client.connect()
    stateLabel.value = '正在读取桌宠状态…'
    const response = await client.request('pet.overview.read')
    overview.value = normalizeOverview(response.overview)
    stateLabel.value = '正在读取桌宠设置…'
    const settingResponse = await client.request('settings.get', { namespace: 'core.pet' })
    Object.assign(settings, defaultPetSettings(settingResponse.value))
    stateLabel.value = '正在读取桌宠资源…'
    const packResponse = await client.request('pet.packs.list')
    packs.value = Array.isArray(packResponse.packs) ? packResponse.packs as PetPack[] : []
    stateLabel.value = overview.value.global_state === 'waiting'
      ? '有事项需要你处理'
      : overview.value.global_state === 'error'
        ? '有任务发生错误'
        : overview.value.global_state === 'running'
          ? '任务运行中'
          : '一切平稳'
  } catch {
    client?.close()
    client = null
    stateLabel.value = '暂时无法连接 Core'
    connectionState.value = 'error'
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (!mounted || reconnectTimer) return
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    void connect()
  }, 2000)
}

function retryNow() {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = null
  void connect()
}

async function saveSettings() {
  if (!client) return
  try {
    await client.request('settings.update', { namespace: 'core.pet', value: { ...settings } })
    await emit('pet-settings-changed', { ...settings })
  } catch {
    stateLabel.value = '设置未保存：Core 未连接'
    connectionState.value = 'error'
    scheduleReconnect()
  }
}

async function toggleEnabled() {
  await saveSettings()
  await invoke(settings.enabled ? 'show_pet_window' : 'hide_pet_window')
  await emit('pet-visibility-changed', { enabled: settings.enabled })
}

async function respond(item: PetInteraction, decision: string, guidance = '') {
  if (!client || responding.value) return
  responding.value = true
  try {
    if (item.type === 'approval') {
      await client.request('approval.respond', {
        thread_id: item.thread_id,
        request_id: item.id,
        decision,
        guidance,
      })
    } else {
      // ask-user is a normal text continuation, exactly like submitting the
      // answer from the Main composer. It is not an approval lifecycle and
      // must not be sent to approval.respond.
      const answer = guidance.trim()
      if (!answer) return
      await client.request('turn/start', {
        thread_id: item.thread_id,
        client_message_id: crypto.randomUUID(),
        input: [{ type: 'text', text: answer }],
        include_snapshot: false,
      }, 60_000)
    }
  } catch {
    stateLabel.value = '操作未送达：Core 未连接'
    connectionState.value = 'error'
    scheduleReconnect()
  } finally {
    responding.value = false
  }
}

async function submitGuidance(item: PetInteraction) {
  const guidance = guidanceDraft.value.trim()
  if (!guidance) return
  await respond(item, 'other_guidance', guidance)
  guidanceDraft.value = ''
  showGuidance.value = false
}

function close() { void invoke('hide_pet_overlay') }
function focusMain() { void invoke('focus_main_window') }
function openSession(threadId: string) {
  void emit('pet-open-session', { thread_id: threadId })
  focusMain()
}

onMounted(async () => {
  mounted = true
  unlistenSettings = await listen<PetSettings>('pet-settings-changed', ({ payload }) => {
    Object.assign(settings, defaultPetSettings(payload))
  })
  unlistenVisibility = await listen<{ enabled: boolean }>('pet-visibility-changed', ({ payload }) => {
    settings.enabled = payload.enabled !== false
  })
  void connect()
})
onBeforeUnmount(() => {
  mounted = false
  if (reconnectTimer) clearTimeout(reconnectTimer)
  unlistenSettings?.()
  unlistenVisibility?.()
  client?.close()
})
</script>

<style>
html, body, #app { width: 100%; height: 100%; margin: 0; overflow: hidden; background: transparent; border-radius: 18px; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #f3eee8; }
.pet-overlay { box-sizing: border-box; width: 100%; height: 100%; min-height: 100%; overflow: auto; padding: 22px; background: rgba(31, 28, 32, .96); background-clip: padding-box; border: 1px solid rgba(255,255,255,.14); border-radius: 18px; box-shadow: 0 18px 50px rgba(0,0,0,.4); }
header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.eyebrow, .card-kind { margin: 0 0 5px; color: #cba477; font-size: 10px; letter-spacing: .14em; font-weight: 700; }
h1 { margin: 0; font-size: 22px; font-weight: 700; }
button, select { border: 1px solid rgba(255,255,255,.14); border-radius: 9px; background: rgba(255,255,255,.08); color: inherit; padding: 8px 10px; cursor: pointer; }
button:hover { background: rgba(255,255,255,.15); }.close { border: 0; padding: 0 4px; font-size: 25px; line-height: 1; background: transparent; }
.section { display: grid; gap: 10px; margin-bottom: 14px; }.card { padding: 13px; border-radius: 12px; background: rgba(255,255,255,.07); }.waiting-card { border-left: 3px solid #e5aa52; }.error-card { border-left: 3px solid #e9685f; }.connection-card { border-left: 3px solid #d39a5f; }.card strong { display: block; margin-bottom: 6px; }.card p { margin: 0; color: #d6cec6; font-size: 13px; line-height: 1.45; }.actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }.guidance-box { display: grid; gap: 7px; margin-top: 10px; }.guidance-box textarea { width: 100%; box-sizing: border-box; resize: vertical; border: 1px solid rgba(255,255,255,.16); border-radius: 9px; background: rgba(0,0,0,.18); color: inherit; padding: 8px; font: inherit; }.primary { background: #b87842; border-color: #d3995e; color: #fff8f0; }button:disabled { cursor: wait; opacity: .55; }.queue-count { margin-bottom: 9px; color: #dcb77f; font-size: 12px; }
.settings { display: grid; gap: 10px; padding: 13px 0; border-top: 1px solid rgba(255,255,255,.1); }.settings label { display: flex; justify-content: space-between; align-items: center; gap: 10px; font-size: 13px; color: #d6cec6; }.settings input[type=range] { width: 150px; accent-color: #d39a5f; }.toggle { justify-content: flex-start !important; }.toggle input { accent-color: #d39a5f; }.main-button { width: 100%; margin-top: 8px; }
</style>
