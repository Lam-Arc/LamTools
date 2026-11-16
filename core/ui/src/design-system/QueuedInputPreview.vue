<script setup lang="ts">
import { nextTick, ref } from 'vue'
import CoreQueuedInputTray, { type CoreQueuedInputTrayItem } from '@/components/CoreQueuedInputTray.vue'

// user:“交互测试”+(队列编辑、排序和引导都只操作本地示例)。
const items = ref<CoreQueuedInputTrayItem[]>([{ id: 'one', text: '整理资料', status: 'queued' }, { id: 'two', text: '检查结果', status: 'queued' }])
const editing = ref<string | null>(null), draft = ref(''), result = ref(''), canGuide = ref(true)
const root = ref<HTMLElement | null>(null)
async function edit(item: CoreQueuedInputTrayItem) { editing.value = item.id; draft.value = item.text; await nextTick(); root.value?.querySelector<HTMLInputElement>('[data-queued-input-edit]')?.focus() }
function save(item: CoreQueuedInputTrayItem) { if (editing.value !== item.id) return; items.value = items.value.map(entry => entry.id === item.id ? { ...entry, text: draft.value } : entry); editing.value = null }
function guide(item: CoreQueuedInputTrayItem) { result.value = item.text; items.value = items.value.filter(entry => entry.id !== item.id) }
</script>

<template>
  <div ref="root" class="queue-example">
    <label><input v-model="canGuide" class="sunday-checkbox" type="checkbox" />允许引导</label>
    <CoreQueuedInputTray v-model:draft="draft" :items="items" :editing-id="editing" :can-guide="canGuide" @edit="edit" @save="save" @cancel="editing = null" @delete="item => items = items.filter(entry => entry.id !== item.id)" @guide="guide" @reorder="items = $event" />
    <span v-if="result">本地引导：{{ result }}</span>
  </div>
</template>

<style scoped>
.queue-example { width: 100%; min-width: 0; }
</style>
