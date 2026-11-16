<script setup lang="ts">
import { reactive, ref } from 'vue'
import CoreSplitPreview from '@/components/CoreSplitPreview.vue'
import type { SplitTab } from '@/split/layout'
import type { LamToolsTransport } from '@/transport'
import '@/styles/split-workspace.css'

// user:“交互测试”+(文件内容、失败及打开动作均在展厅本地模拟)。
const tab = reactive<SplitTab>({ id: 'gallery-file-preview', kind: 'preview', resource: '示例.md', title: '示例.md' })
const fail = ref(false)
const opened = ref(false)
const transport = {
  async request(request: { method?: string; path: string }) {
    if (request.method === 'POST' && request.path === '/files/open-reference') { opened.value = true; return { status: 200, body: new Uint8Array() } }
    if (request.method === 'GET' && request.path.startsWith('/files/read-reference?')) {
      const path = new URLSearchParams(request.path.split('?')[1]).get('path') || ''
      return fail.value
        ? { status: 500, body: new TextEncoder().encode(JSON.stringify({ detail: '示例读取失败' })) }
        : { status: 200, body: new TextEncoder().encode(path.endsWith('.md') ? '# 示例标题\n\n这是本地预览。' : path.endsWith('.svg') ? '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="100"><rect width="160" height="100" rx="12" fill="#79bcff"/><circle cx="80" cy="50" r="24" fill="#1f1f1f"/></svg>' : '示例纯文本') }
    }
    throw new Error('展厅不支持此操作')
  },
} as unknown as LamToolsTransport
</script>

<template>
  <div class="file-preview-example">
    <div class="file-preview-actions">
      <button class="btn btn--secondary" type="button" @click="tab.resource = '示例.md'">Markdown 示例</button>
      <button class="btn btn--secondary" type="button" @click="tab.resource = '示例.txt'">文本示例</button>
      <button class="btn btn--secondary" type="button" @click="tab.resource = '示例.svg'">图片示例</button>
      <label><input v-model="fail" class="sunday-checkbox" type="checkbox" />模拟读取失败</label>
    </div>
    <div class="file-preview-shell" data-gallery-file-preview><CoreSplitPreview :tab="tab" root="" :transport="transport" /></div>
    <span v-if="opened">本地模拟打开</span>
  </div>
</template>

<style scoped>
.file-preview-example { width: 100%; display: grid; gap: var(--space-3); }
.file-preview-actions { display: flex; align-items: center; gap: var(--space-2); }
.file-preview-shell { height: 360px; min-width: 0; overflow: hidden; border: 1px solid var(--theme-main-border); border-radius: var(--radius); }
</style>
