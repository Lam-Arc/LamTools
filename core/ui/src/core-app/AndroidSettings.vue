/**
 * The model settings screen for Android.
 *
 * Deliberately separate from the desktop `CoreSettings.vue`: that screen edits a provider
 * catalogue owned by the desktop core, and this host has one endpoint and one key. Joining
 * them would mean one component with two backends and a branch in every handler.
 *
 * Three things it refuses to do, because the backend does:
 *
 *  - it never receives the key, so it cannot show or log one;
 *  - it cannot approve an endpoint by editing the address: the backend clears the
 *    approval when the address changes, and this screen asks again;
 *  - it does not pretend a key was stored when the keystore refused. The error is shown
 *    as it came back.
 */
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'

type CredentialStorage = {
  kind: string
  reason?: string | null
  needs_migration: boolean
  has_key: boolean
}

type ModelConfig = {
  base_url: string
  model_id: string
  provider: string
  granted_tools: string[]
  has_api_key: boolean
  allow_insecure_local: boolean
  endpoint_approved: boolean
  endpoint_prompt?: string | null
  credential_storage: CredentialStorage
  restart_required?: boolean
}

type ToolEntry = {
  id: string
  description: string
  side_effect: string
  permission: string
  granted: boolean
}

const PROVIDERS = [
  { id: 'openai-compatible', label: '自建 / 兼容端点' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'anthropic', label: 'Anthropic' },
]

const config = ref<ModelConfig | null>(null)
const tools = ref<ToolEntry[]>([])
const key = ref('')
const busy = ref('')
const error = ref('')
const note = ref('')

const storageLabel = computed(() => {
  const storage = config.value?.credential_storage
  if (!storage) return ''
  if (storage.kind === 'android-keystore') return 'Android KeyStore（系统密钥库）'
  if (storage.kind === 'owner-only-file') return '仅属主可读的文件（桌面包）'
  return '不可用'
})

const storageTone = computed(() => {
  const kind = config.value?.credential_storage.kind
  if (kind === 'android-keystore') return 'ok'
  if (kind === 'owner-only-file') return 'warn'
  return 'bad'
})

async function reload(): Promise<void> {
  config.value = await invoke<ModelConfig>('model_config')
  const catalog = await invoke<{ tools: ToolEntry[] }>('tool_catalog')
  tools.value = catalog.tools
}

function describeError(cause: unknown): string {
  if (typeof cause === 'string') return cause
  if (cause instanceof Error) return cause.message
  return String(cause)
}

async function run<T>(label: string, action: () => Promise<T>): Promise<T | null> {
  busy.value = label
  error.value = ''
  note.value = ''
  try {
    return await action()
  } catch (cause) {
    error.value = describeError(cause)
    return null
  } finally {
    busy.value = ''
  }
}

async function saveModel(): Promise<void> {
  if (!config.value) return
  const current = config.value
  const updated = await run('save', () =>
    invoke<ModelConfig>('save_model_config', {
      patch: {
        provider: current.provider,
        base_url: current.base_url,
        model_id: current.model_id,
        allow_insecure_local: current.allow_insecure_local,
      },
    }),
  )
  if (updated) {
    config.value = updated
    note.value = updated.restart_required
      ? '已保存。模型设置在重启应用后生效。'
      : '已保存。'
    await reload()
  }
}

async function approveEndpoint(): Promise<void> {
  const updated = await run('approve', () => invoke<ModelConfig>('approve_endpoint'))
  if (updated) {
    note.value = '已批准该地址。重启应用后生效。'
    await reload()
  }
}

async function saveKey(): Promise<void> {
  const entered = key.value.trim()
  if (!entered) {
    error.value = '请先填写 API Key'
    return
  }
  const updated = await run('key', () => invoke<ModelConfig>('set_api_key', { key: entered }))
  if (updated) {
    key.value = ''
    note.value = '已保存密钥。地址需要重新确认后才会发送。'
    await reload()
  }
}

async function clearKey(): Promise<void> {
  const updated = await run('clear', () => invoke<ModelConfig>('clear_api_key'))
  if (updated) {
    note.value = '已删除密钥。'
    await reload()
  }
}

async function toggleGrant(tool: ToolEntry): Promise<void> {
  const catalog = await run('grant', () =>
    invoke<{ tools: ToolEntry[] }>('set_tool_grant', {
      toolId: tool.id,
      granted: !tool.granted,
    }),
  )
  if (catalog) {
    tools.value = catalog.tools
    note.value = `已${tool.granted ? '撤销' : '授予'} ${tool.id} 的免询问权限。`
  }
}

onMounted(() => {
  void run('load', reload)
})
</script>

<template>
  <div class="android-settings">
    <section>
      <h2>模型</h2>
      <label>
        <span>供应商</span>
        <select v-model="config.provider" :disabled="!!busy">
          <option v-for="provider in PROVIDERS" :key="provider.id" :value="provider.id">
            {{ provider.label }}
          </option>
        </select>
      </label>
      <label>
        <span>接口地址</span>
        <input v-model="config.base_url" :disabled="!!busy" placeholder="https://api.example.com/v1" />
      </label>
      <label>
        <span>模型</span>
        <input v-model="config.model_id" :disabled="!!busy" placeholder="qwen2.5:3b" />
      </label>
      <label class="inline">
        <input v-model="config.allow_insecure_local" type="checkbox" :disabled="!!busy" />
        <span>允许本地明文 HTTP（仅用于本机或局域网模型）</span>
      </label>
      <button :disabled="!!busy" @click="saveModel">保存模型设置</button>
    </section>

    <section>
      <h2>端点确认</h2>
      <!-- The headline is written here so it is in the user's language. The core's own
           wording stays available underneath, because that is the authoritative reason
           and support needs it verbatim. -->
      <p v-if="config?.endpoint_approved && !config?.has_api_key" class="ok">
        该地址可用。未配置密钥，将直接连接这个地址。
      </p>
      <p v-else-if="config?.endpoint_approved" class="ok">
        密钥已绑定到 {{ config.base_url }}，可以发往该地址。
      </p>
      <template v-else>
        <p class="warn">
          该地址尚未批准：{{ config?.base_url }}。批准之前，密钥不会发往任何地址。
        </p>
        <details v-if="config?.endpoint_prompt">
          <summary>核心给出的具体原因</summary>
          <pre>{{ config.endpoint_prompt }}</pre>
        </details>
        <button :disabled="!!busy" @click="approveEndpoint">批准当前地址</button>
      </template>
    </section>

    <section>
      <h2>API Key</h2>
      <p :class="storageTone">存储：{{ storageLabel }}</p>
      <p v-if="config?.credential_storage.reason" class="bad">
        {{ config.credential_storage.reason }}
      </p>
      <p v-if="config?.credential_storage.needs_migration" class="warn">
        检测到旧版明文密钥，首次读取时会自动迁移进密钥库。
      </p>
      <p v-if="config?.has_api_key" class="ok">已保存密钥（不会显示出来）。</p>
      <label>
        <span>{{ config?.has_api_key ? '替换密钥' : '填写密钥' }}</span>
        <input v-model="key" type="password" :disabled="!!busy" autocomplete="off" />
      </label>
      <div class="row">
        <button :disabled="!!busy" @click="saveKey">保存密钥</button>
        <button :disabled="!!busy || !config?.has_api_key" class="secondary" @click="clearKey">
          删除密钥
        </button>
      </div>
    </section>

    <section>
      <h2>工具权限</h2>
      <p class="hint">只读工具默认放行。有副作用的工具默认每次询问，这里可以逐个授权免询问。</p>
      <ul class="tools">
        <li v-for="tool in tools" :key="tool.id">
          <div>
            <strong>{{ tool.id }}</strong>
            <span class="tag">{{ tool.side_effect }}</span>
            <p>{{ tool.description }}</p>
          </div>
          <label class="switch">
            <input
              type="checkbox"
              :checked="tool.granted"
              :disabled="!!busy"
              @change="toggleGrant(tool)"
            />
            <span>免询问</span>
          </label>
        </li>
      </ul>
      <p v-if="!tools.length" class="hint">核心没有报告任何工具。</p>
    </section>

    <p v-if="error" class="bad">{{ error }}</p>
    <p v-if="note" class="ok">{{ note }}</p>
    <p v-if="busy" class="hint">处理中：{{ busy }}</p>
  </div>
</template>

<style scoped>
.android-settings {
  padding: 16px 16px 96px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  color: var(--foreground, #e6e8eb);
}
section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
h2 {
  font-size: 15px;
  margin: 0;
  font-weight: 600;
}
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
label.inline {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
input,
select {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border, #2f3540);
  background: var(--control, #1b1f26);
  color: inherit;
  font: inherit;
}
button {
  align-self: flex-start;
  padding: 10px 16px;
  border-radius: 8px;
  border: 1px solid var(--border, #2f3540);
  background: var(--control, #232830);
  color: inherit;
  font: inherit;
}
button.secondary {
  opacity: 0.75;
}
button:disabled {
  opacity: 0.45;
}
.row {
  display: flex;
  gap: 10px;
}
.ok {
  color: #7ddc9b;
  font-size: 13px;
  margin: 0;
}
.warn {
  color: #e8c26a;
  font-size: 13px;
  margin: 0;
}
.bad {
  color: #f08a8a;
  font-size: 13px;
  margin: 0;
}
.hint {
  color: #9aa4b2;
  font-size: 12px;
  margin: 0;
}
details {
  font-size: 12px;
  color: #9aa4b2;
}
details pre {
  margin: 6px 0 0;
  white-space: pre-wrap;
  font: 12px/1.5 ui-monospace, monospace;
}
.tools {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tools li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--border, #2f3540);
  border-radius: 10px;
}
.tools p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #9aa4b2;
}
.tag {
  margin-left: 8px;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 999px;
  background: #232830;
  color: #9aa4b2;
}
.switch {
  flex-direction: row;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
</style>
