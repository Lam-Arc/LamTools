<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>生图</h1>
      <p>启用后 generate_image 工具才会上传工具集；未启用时调用会被拦截。</p>
    </header>

    <p v-if="error" class="skill-error" role="alert">{{ error }}</p>

    <article class="setting-card agent-toggle">
      <div class="agent-toggle-row">
        <div>
          <h3>启用 generate_image 工具</h3>
          <p>关闭后工具从工具集移除；启用但 API 地址为空时，调用返回“未配置生图 API”。</p>
        </div>
        <button
          class="text-btn"
          :class="{ 'is-on': form.enabled }"
          type="button"
          @click="toggleEnabled"
        >{{ form.enabled ? '已开启' : '已关闭' }}</button>
      </div>
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">API 配置</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading" @click="fetchConfig">刷新</button>
          <button class="text-btn" type="button" :disabled="loading || saving" @click="saveConfig">保存</button>
        </div>
      </div>

      <label class="field">
        <span>API 地址 <em>必填</em></span>
        <input
          v-model="form.api_url"
          type="url"
          spellcheck="false"
          placeholder="https://api.example.com/v1"
          :disabled="loading || saving"
        />
      </label>

      <label class="field">
        <span>API Key</span>
        <input
          v-model="form.api_key"
          type="password"
          spellcheck="false"
          placeholder="sk-..."
          autocomplete="off"
          :disabled="loading || saving"
        />
      </label>

      <label class="field">
        <span>模型</span>
        <input
          v-model="form.model"
          type="text"
          spellcheck="false"
          placeholder="如 gpt-image-1 / flux 等，留空使用服务端默认"
          :disabled="loading || saving"
        />
      </label>

      <p v-if="saved" class="hook-meta" role="status"><Check :size="12" :stroke-width="2.2" aria-hidden="true" /> 已保存</p>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Check } from 'lucide-vue-next'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const NAMESPACE = 'core.imagegen'

const form = reactive({
  enabled: false,
  api_url: '',
  api_key: '',
  model: '',
})
const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const error = ref('')

async function fetchConfig() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('settings.get', { namespace: NAMESPACE })
    const value = result.value as Record<string, unknown> | undefined
    form.enabled = value ? !!value.enabled : false
    form.api_url = value ? String(value.api_url || '') : ''
    form.api_key = value ? String(value.api_key || '') : ''
    form.model = value ? String(value.model || '') : ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function toggleEnabled() {
  const next = !form.enabled
  form.enabled = next
  saved.value = false
  try {
    await props.requestRpc('settings.update', {
      namespace: NAMESPACE,
      value: { enabled: next },
    })
    saved.value = true
  } catch (e) {
    form.enabled = !next
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function saveConfig() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    await props.requestRpc('settings.update', {
      namespace: NAMESPACE,
      value: {
        enabled: form.enabled,
        api_url: form.api_url.trim(),
        api_key: form.api_key.trim(),
        model: form.model.trim(),
      },
    })
    saved.value = true
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

onMounted(fetchConfig)
</script>

<style scoped>
.agent-toggle {
  padding: 12px 14px;
}

.agent-toggle-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
}

.agent-toggle h3 {
  margin: 0 0 4px;
  font-size: 14px;
}

.agent-toggle p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.text-btn.is-on {
  color: var(--green);
}

.skill-error {
  margin: 0;
  padding: 9px 12px;
  border-radius: var(--radius);
  border: 1px solid color-mix(in srgb, var(--red) 22%, transparent);
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: color-mix(in srgb, var(--red) 64%, var(--settings-main-text, #fff));
  font-size: 13px;
}

.field {
  display: grid;
  gap: 5px;
  margin-bottom: 13px;
}

.field > span {
  font-size: 12px;
  font-weight: 600;
}

.field em {
  color: var(--red, #e5484d);
  font-style: normal;
  font-weight: 400;
}

.field input {
  width: 100%;
  padding: 7px 10px;
  border-radius: var(--radius-sm, 8px);
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 5%, transparent);
  color: var(--settings-main-text, #fff);
  font-size: 13px;
}

.hook-meta {
  margin: 0;
  font-size: 12px;
  color: var(--green);
}
</style>
