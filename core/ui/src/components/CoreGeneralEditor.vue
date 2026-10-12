<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>通用</h1>
      <p>全应用的出口流量走哪里，以及它们信任哪个根证书。</p>
    </header>

    <p v-if="error" class="general-error" role="alert">{{ error }}</p>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">HTTP 代理</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading" @click="fetchConfig">刷新</button>
          <button class="text-btn" type="button" :disabled="loading || busy" @click="saveField('proxy')">保存</button>
        </div>
      </div>
      <p class="general-hint">
        模型、MCP、命令工具、网页抓取与搜索、插件安装、软件更新下载的出口流量都将经此代理；
        应用界面内的网页（渲染层）跟随系统代理设置。留空时这些流量直连，不读取系统环境变量。
        本机地址（localhost、127.0.0.1、::1）始终直连。
      </p>
      <label class="field">
        <input
          v-model="form.proxy"
          type="text"
          spellcheck="false"
          autocomplete="off"
          placeholder="例如 http://127.0.0.1:7890"
          aria-label="HTTP 代理"
          :disabled="loading || busy"
          @keyup.enter="saveField('proxy')"
        />
      </label>
      <p v-if="savedField === 'proxy'" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" /> 已保存
      </p>
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">不使用代理的地址</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading || busy" @click="saveField('no_proxy')">保存</button>
        </div>
      </div>
      <p class="general-hint">
        匹配这些主机的请求将直连，不经过 HTTP 代理；命令工具按同一份规则写入 NO_PROXY。
        多个规则用英文逗号分隔。
      </p>
      <label class="field">
        <input
          v-model="form.no_proxy"
          type="text"
          spellcheck="false"
          autocomplete="off"
          placeholder="例如 localhost,127.0.0.1,::1,.example.com,*.corp.com"
          aria-label="不使用代理的地址"
          :disabled="loading || busy"
          @keyup.enter="saveField('no_proxy')"
        />
      </label>
      <p v-if="savedField === 'no_proxy'" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" /> 已保存
      </p>
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">自定义证书</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading || busy" @click="saveField('ca_cert')">保存</button>
        </div>
      </div>
      <p class="general-hint">
        可选。填写 PEM 根证书路径后，模型请求以它为信任根，并以 SSL_CERT_FILE、NODE_EXTRA_CA_CERTS
        等变量注入 MCP 与命令工具；留空则使用系统信任链。
      </p>
      <label class="field">
        <input
          v-model="form.ca_cert"
          type="text"
          spellcheck="false"
          autocomplete="off"
          placeholder="例如 C:\certs\root-ca.pem"
          aria-label="自定义证书"
          :disabled="loading || busy"
          @keyup.enter="saveField('ca_cert')"
        />
      </label>
      <p v-if="savedField === 'ca_cert'" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" /> 已保存
      </p>
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">提问自动继续</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading || busy" @click="fetchAskAutoContinue">刷新</button>
        </div>
      </div>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">
          打开后，模型的提问卡超过 5 分钟无人回答，会按「用户跳过」回传，本轮继续往下走。
          需要你授权的审批卡不受影响，会一直等你处理。
        </p>
        <button
          class="text-btn toggle-btn"
          :class="{ 'is-on': askAutoContinue }"
          type="button"
          aria-label="提问自动继续"
          :aria-pressed="askAutoContinue"
          :title="askAutoContinue ? '已打开' : '已关闭'"
          :disabled="loading || busy"
          @click="toggleAskAutoContinue"
        >
          <ToggleRight v-if="askAutoContinue" :size="16" :stroke-width="1.8" aria-hidden="true" />
          <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
    </article>

    <article v-if="keepAwakeSupported" class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">保持电脑运行</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading || busy" @click="fetchKeepAwake">刷新</button>
        </div>
      </div>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">
          打开后阻止系统进入空闲休眠（手动睡眠、合盖休眠不受影响），长任务不会被中断。
        </p>
        <button
          class="text-btn toggle-btn"
          :class="{ 'is-on': keepAwake }"
          type="button"
          aria-label="保持电脑运行"
          :aria-pressed="keepAwake"
          :title="keepAwake ? '已打开' : '已关闭'"
          :disabled="loading || busy"
          @click="toggleKeepAwake"
        >
          <ToggleRight v-if="keepAwake" :size="16" :stroke-width="1.8" aria-hidden="true" />
          <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
    </article>

    <article v-if="memoryResumeSupported" class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">内存中断自动续跑</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading || memoryResumeBusy" @click="fetchMemoryResume">刷新</button>
          <button class="text-btn" type="button" :disabled="loading || memoryResumeBusy" @click="saveMemoryThreshold">保存</button>
        </div>
      </div>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">
          机器内存不足导致本轮中断时，Sunday 会说明原因，并写明「可用内存大于多少就自动继续」；
          内存回来后在同一会话自动开新一轮接着做，最多连续 3 次。你自己先发了新消息时不再自动继续。
        </p>
        <button
          class="text-btn toggle-btn"
          :class="{ 'is-on': memoryResume }"
          type="button"
          aria-label="内存中断自动续跑"
          :aria-pressed="memoryResume"
          :title="memoryResume ? '已打开' : '已关闭'"
          :disabled="loading || memoryResumeBusy"
          @click="toggleMemoryResume"
        >
          <ToggleRight v-if="memoryResume" :size="16" :stroke-width="1.8" aria-hidden="true" />
          <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
      <p class="general-hint">
        自动继续的内存阈值（GB）：可用内存 = 物理内存 + 页面文件还能分配的量。调高更保守，但要等更久。
      </p>
      <label class="field">
        <input
          v-model="memoryThresholdDraft"
          type="number"
          min="0.5"
          max="1024"
          step="0.5"
          inputmode="decimal"
          aria-label="自动继续的内存阈值（GB）"
          :disabled="loading || memoryResumeBusy"
          @keyup.enter="saveMemoryThreshold"
        />
      </label>
      <p v-if="memoryResumeSaved" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" /> 已保存
      </p>
    </article>

    <p class="general-hint general-hint--foot">
      保存后新发起的模型、MCP 与命令调用立即按新设置走；已连接的 MCP 服务与已运行的后台命令需重启应用。
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Check, ToggleLeft, ToggleRight } from 'lucide-vue-next'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  /** Mirrors the settings shell: the keep-awake switch exists on Windows only. */
  platform?: 'windows' | 'linux' | 'mobile' | 'web' | 'other'
}>()

const NAMESPACE = 'core.network'
const KEEP_AWAKE_NAMESPACE = 'core.keepAwake'
const ASK_AUTO_CONTINUE_NAMESPACE = 'core.askAutoContinue'
const MEMORY_RESUME_NAMESPACE = 'core.memoryResume'

// Mirrors the backend defaults in runtime/memory_guard.py: an unset namespace
// means「开着，阈值 4 GB」, so the card must not read an empty value as "off".
const MEMORY_RESUME_DEFAULT_THRESHOLD_GB = 4

type FieldKey = 'proxy' | 'no_proxy' | 'ca_cert'

const form = reactive({ proxy: '', no_proxy: '', ca_cert: '' })
const loading = ref(true)
const busyKeys = ref<FieldKey[]>([])
const savedField = ref<FieldKey | ''>('')
const error = ref('')
const keepAwake = ref(false)
const keepAwakeSaving = ref(false)
const askAutoContinue = ref(false)
const askAutoContinueSaving = ref(false)
const memoryResume = ref(true)
const memoryResumeSaving = ref(false)
const memoryThresholdDraft = ref(String(MEMORY_RESUME_DEFAULT_THRESHOLD_GB))
const memoryResumeSaved = ref(false)

const busy = computed(() => busyKeys.value.length > 0 || keepAwakeSaving.value || askAutoContinueSaving.value)
const keepAwakeSupported = computed(() => (props.platform ?? 'other') === 'windows')
/** The host-memory reading exists on Windows and Linux; elsewhere the feature is inert. */
const memoryResumeSupported = computed(
  () => (props.platform ?? 'other') === 'windows' || (props.platform ?? 'other') === 'linux',
)
const memoryResumeBusy = computed(() => memoryResumeSaving.value || busy.value)

function readValue(result: Record<string, unknown>): Record<string, unknown> {
  const value = result.value
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

async function fetchConfig() {
  loading.value = true
  error.value = ''
  savedField.value = ''
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: NAMESPACE }))
    form.proxy = String(value.proxy ?? '')
    form.no_proxy = String(value.no_proxy ?? '')
    form.ca_cert = String(value.ca_cert ?? '')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function saveField(key: FieldKey) {
  if (loading.value || busy.value) return
  const next = form[key].trim()
  const previous = form[key]
  form[key] = next
  savedField.value = ''
  error.value = ''
  busyKeys.value = [...busyKeys.value, key]
  try {
    await props.requestRpc('settings.update', { namespace: NAMESPACE, value: { [key]: next } })
    savedField.value = key
  } catch (e) {
    // The backend validates the field; restore the last known-good value and
    // never claim the draft was stored.
    error.value = e instanceof Error ? e.message : String(e)
    form[key] = previous
  } finally {
    busyKeys.value = busyKeys.value.filter((item) => item !== key)
  }
}

onMounted(fetchConfig)

async function fetchKeepAwake() {
  if (!keepAwakeSupported.value) return
  error.value = ''
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: KEEP_AWAKE_NAMESPACE }))
    keepAwake.value = !!value.enabled
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggleKeepAwake() {
  if (!keepAwakeSupported.value || keepAwakeSaving.value) return
  const next = !keepAwake.value
  const previous = keepAwake.value
  keepAwake.value = next
  keepAwakeSaving.value = true
  error.value = ''
  try {
    await props.requestRpc('settings.update', {
      namespace: KEEP_AWAKE_NAMESPACE,
      value: { enabled: next },
    })
  } catch (e) {
    keepAwake.value = previous
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    keepAwakeSaving.value = false
  }
}

onMounted(fetchKeepAwake)


async function fetchAskAutoContinue() {
  error.value = ''
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: ASK_AUTO_CONTINUE_NAMESPACE }))
    askAutoContinue.value = !!value.enabled
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggleAskAutoContinue() {
  if (askAutoContinueSaving.value) return
  const next = !askAutoContinue.value
  const previous = askAutoContinue.value
  askAutoContinue.value = next
  askAutoContinueSaving.value = true
  error.value = ''
  try {
    await props.requestRpc('settings.update', {
      namespace: ASK_AUTO_CONTINUE_NAMESPACE,
      value: { enabled: next },
    })
  } catch (e) {
    askAutoContinue.value = previous
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    askAutoContinueSaving.value = false
  }
}

onMounted(fetchAskAutoContinue)


function readMemoryThreshold(value: Record<string, unknown>): number {
  const raw = value.threshold_gb
  if (typeof raw !== 'number' || !Number.isFinite(raw) || raw <= 0) {
    return MEMORY_RESUME_DEFAULT_THRESHOLD_GB
  }
  return raw
}

async function fetchMemoryResume() {
  if (!memoryResumeSupported.value) return
  error.value = ''
  memoryResumeSaved.value = false
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: MEMORY_RESUME_NAMESPACE }))
    // Absent namespace = the backend default (on, 4 GB), not "off".
    memoryResume.value = value.enabled === undefined ? true : !!value.enabled
    memoryThresholdDraft.value = String(readMemoryThreshold(value))
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggleMemoryResume() {
  if (!memoryResumeSupported.value || memoryResumeBusy.value) return
  const next = !memoryResume.value
  const previous = memoryResume.value
  memoryResume.value = next
  memoryResumeSaving.value = true
  memoryResumeSaved.value = false
  error.value = ''
  try {
    await props.requestRpc('settings.update', {
      namespace: MEMORY_RESUME_NAMESPACE,
      value: { enabled: next },
    })
  } catch (e) {
    memoryResume.value = previous
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    memoryResumeSaving.value = false
  }
}

async function saveMemoryThreshold() {
  if (!memoryResumeSupported.value || memoryResumeBusy.value) return
  const parsed = Number(memoryThresholdDraft.value)
  if (!Number.isFinite(parsed) || parsed < 0.5 || parsed > 1024) {
    error.value = '阈值需要是 0.5 到 1024 之间的数字（GB）'
    return
  }
  const previous = memoryThresholdDraft.value
  memoryResumeSaving.value = true
  memoryResumeSaved.value = false
  error.value = ''
  try {
    await props.requestRpc('settings.update', {
      namespace: MEMORY_RESUME_NAMESPACE,
      value: { threshold_gb: parsed },
    })
    memoryThresholdDraft.value = String(parsed)
    memoryResumeSaved.value = true
  } catch (e) {
    // The backend validates; keep the last known-good value rather than
    // pretending the draft was stored.
    memoryThresholdDraft.value = previous
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    memoryResumeSaving.value = false
  }
}

onMounted(fetchMemoryResume)
</script>

<style scoped>
.general-hint {
  margin: 0 0 var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 62%, transparent);
  font-size: 12px;
  line-height: 1.6;
}

.general-hint--foot {
  margin: 0;
  padding: 0 var(--space-1);
}

.general-toggle-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-3);
  align-items: center;
}

.general-hint--inline {
  margin: 0;
}

.text-btn.is-on {
  color: var(--green);
}

.general-saved {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0;
  color: var(--green);
  font-size: 12px;
}

.general-error {
  margin: 0;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--red) 22%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: color-mix(in srgb, var(--red) 64%, var(--settings-main-text, #fff));
  font-size: 13px;
}
</style>
