<!--
  First-run configuration for the Android host.

  user:"配置模型并进行真实对话"+(首次打开必须能把地址、模型和密钥填进 Core 自己的
  配置里；宿主不另造一套设置，写的就是 Core 启动时会读的那份文件)。

  This is not the desktop settings screen. Desktop edits a provider catalogue; a phone
  has one endpoint and one key, and asking the user to manage several on a 6-inch screen
  would be pretending the two surfaces are the same. The core still owns validation, so
  what lands here is exactly what the desktop app would accept.
-->
<template>
  <div class="setup">
    <h1>连接模型</h1>
    <p class="hint">
      Sunday 在本机运行完整的 Core，用的是随包的 Python 运行时。填写一个 OpenAI 兼容端点即可开始。
    </p>

    <label>
      <span>接口地址</span>
      <input
        v-model="baseUrl"
        type="url"
        inputmode="url"
        autocomplete="off"
        placeholder="https://api.example.com/v1"
        :disabled="saving"
      />
    </label>
    <label>
      <span>模型 ID</span>
      <input
        v-model="modelId"
        type="text"
        autocomplete="off"
        placeholder="deepseek-v4.1-flash"
        :disabled="saving"
      />
    </label>
    <label>
      <span>API Key</span>
      <input
        v-model="apiKey"
        type="password"
        autocomplete="off"
        placeholder="sk-..."
        :disabled="saving"
      />
    </label>
    <label>
      <span>显示名称（可选）</span>
      <input v-model="displayName" type="text" autocomplete="off" :disabled="saving" />
    </label>

    <button type="button" :disabled="saving || !baseUrl || !modelId || !apiKey" @click="save">
      {{ saving ? '保存中…' : '保存并重启核心' }}
    </button>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="saved" class="ok">已保存，正在重启核心…</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'

const baseUrl = ref('')
const modelId = ref('')
const apiKey = ref('')
const displayName = ref('')
const saving = ref(false)
const error = ref('')
const saved = ref(false)

async function save(): Promise<void> {
  saving.value = true
  error.value = ''
  try {
    await invoke('configure_model', {
      baseUrl: baseUrl.value.trim(),
      modelId: modelId.value.trim(),
      apiKey: apiKey.value.trim(),
      displayName: displayName.value.trim() || null,
    })
    saved.value = true
    // The core reads its configuration at startup, so the honest way to apply a change
    // is to restart it rather than hope a hot path reloads. Reloading the page also
    // re-runs the boot sequence, which is the code that just worked.
    await invoke('core_stop').catch(() => undefined)
    setTimeout(() => window.location.reload(), 400)
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : String(failure)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.setup {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 28px 20px 40px;
  max-width: 520px;
  margin: 0 auto;
  color: var(--foreground, #e6e8eb);
  background: var(--background, #14161a);
  min-height: 100vh;
  box-sizing: border-box;
}
h1 {
  font-size: 20px;
  margin: 8px 0 0;
  font-weight: 600;
}
.hint {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #9aa4b2;
}
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: #b6bfcc;
}
input {
  padding: 11px 12px;
  border-radius: 10px;
  border: 1px solid var(--border, #2f3540);
  background: var(--control, #1b1f26);
  color: inherit;
  font-size: 15px;
}
input:focus {
  outline: 2px solid #4b67b4;
  outline-offset: 1px;
}
button {
  margin-top: 6px;
  padding: 13px 16px;
  border-radius: 12px;
  border: 1px solid #3a5bb5;
  background: #33509e;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
button:disabled {
  opacity: 0.5;
}
.error {
  color: #f08a8a;
  font-size: 13px;
  white-space: pre-wrap;
}
.ok {
  color: #7ddc9b;
  font-size: 13px;
}
</style>
