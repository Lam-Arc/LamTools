<script setup lang="ts">
import { ref } from 'vue'
import CoreSkillsEditor from '@/components/CoreSkillsEditor.vue'
import CoreHooksEditor from '@/components/CoreHooksEditor.vue'

// user:“交互测试”+(技能和钩子的读取及操作只使用展厅内存，未实现的写入明确失败)。
defineProps<{ view: 'skills' | 'hooks' }>()
const action = ref('')
const skill = { name: 'sample-skill', description: '示例技能', location: '', source: 'user', enabled: true, deletable: true, group: '' }
const hook = { id: 'sample-hook', event: 'PreToolUse', matcher: '*', source: 'user', source_name: 'config', plugin_name: '', config_path: '', handler_type: 'command', command: '示例命令', definition_hash: '', trusted: false, status: 'pending_review' }
async function rpc(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  if (method === 'skill.list') return { skills: [structuredClone(skill)], groups: ['示例分组'], usage_summary: { total_calls: 0, skills_used: 0 } }
  if (method === 'hook.list') return { hooks: [structuredClone(hook)], total_count: 1, trusted_count: Number(hook.trusted), trustable_count: Number(!hook.trusted) }
  action.value = method
  if (method === 'skill.enable' || method === 'skill.disable') { skill.enabled = method === 'skill.enable'; return {} }
  if (method === 'skill.group.assign') { skill.group = String(params.group || ''); return {} }
  if (method === 'hook.trust' || method === 'hook.untrust') { hook.trusted = method === 'hook.trust'; hook.status = hook.trusted ? 'trusted' : 'pending_review'; return {} }
  throw new Error('展厅示例不支持此操作')
}
</script>

<template>
  <div class="skills-hooks-preview">
    <CoreSkillsEditor v-if="view === 'skills'" :request-rpc="rpc" />
    <CoreHooksEditor v-else :request-rpc="rpc" />
    <span v-if="action">本地操作：{{ action }}</span>
  </div>
</template>

<style scoped>
.skills-hooks-preview { display: grid; gap: var(--space-3); width: 100%; }
</style>
