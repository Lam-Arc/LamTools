<script setup lang="ts">
import { ref } from 'vue'
import DirectCallView from '@/components/DirectCallView.vue'

// user:“交互测试”+(模型、调用和历史均为本地示例，不调用模型或读写真实参数)。
const models = [
  { model_record_id: 'sample-text', model_id: 'text', display_name: '示例文本模型', provider_id: 'sample', provider_name: '示例', output_type: 'text', has_api_key: true },
  { model_record_id: 'sample-image', model_id: 'image', display_name: '示例图片模型', provider_id: 'sample', provider_name: '示例', output_type: 'image', has_api_key: true },
]
let call: Record<string, any> | null = null
const failHistory = ref(false)
async function rpc(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  if (method === 'direct.catalog') return { models: structuredClone(models), imagegen: { configured: false } }
  if (method === 'direct.list') {
    if (failHistory.value) throw new Error('示例历史读取失败')
    return { calls: call && (!params.output_type || params.output_type === call.output_type) ? [structuredClone(call)] : [] }
  }
  if (method === 'direct.run') {
    const model = models.find(item => item.model_record_id === params.model_ref) || models[0]
    const prompts = Array.isArray(params.prompts) ? params.prompts as string[] : []
    call = { id: 'sample-call', ...model, status: 'completed', finished: true, prompts, system: '', params: params.params || {}, created_at: '2026-01-01T00:00:00', results: prompts.map((prompt, index) => ({ index, prompt, status: 'ok', text: '示例回答', files: [], error: '', usage: {}, duration_ms: 0 })) }
    return { call: structuredClone(call) }
  }
  if (method === 'direct.get' || method === 'direct.retry') return { call: structuredClone(call) }
  if (method === 'direct.delete') { call = null; return {} }
  if (method === 'direct.save') return { artifacts: [] }
  throw new Error('展厅示例不支持此操作')
}
</script>

<template>
  <div class="direct-call-preview"><label><input v-model="failHistory" type="checkbox" class="sunday-checkbox" />模拟历史读取失败</label><DirectCallView :request-rpc="rpc" project-id="sample" :persist-parameters="false" /></div>
</template>

<style scoped>
.direct-call-preview { width: 100%; height: 650px; overflow: auto; }
</style>
