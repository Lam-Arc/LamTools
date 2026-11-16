<script setup lang="ts">
import { ref } from 'vue'
import CoreExecutionControls from '@/components/CoreExecutionControls.vue'
import CoreWorkspaceMenu from '@/components/CoreWorkspaceMenu.vue'
import type { CorePermissionPreset, CoreThinkingMode, CoreModelCatalogView } from '@/composer/execution'

// user:“交互测试”+(模型、权限和运行模式只更新展厅内存)。
const model = ref('model-a'), thinking = ref<CoreThinkingMode>('high'), permission = ref<CorePermissionPreset>('ask'), mode = ref('normal'), catalog = ref<CoreModelCatalogView>('provider'), disabled = ref(false), workspace = ref('workspace-a')
const models = [{ value: 'model-a', label: '示例模型 A', group: '示例供应商', groupKey: 'provider:sample' }, { value: 'model-b', label: '示例模型 B', group: '示例供应商', groupKey: 'provider:sample' }]
const levels: Array<{ value: CoreThinkingMode; label: string }> = [{ value: 'off', label: '关闭' }, { value: 'medium', label: '中' }, { value: 'high', label: '高' }]
</script>

<template>
  <div class="execution-example">
    <label><input v-model="disabled" class="sunday-checkbox" type="checkbox" />禁用执行选项</label>
    <!-- user:“通过参数、变体和组合保留必要差异”+(在真实插槽中组合工作环境选择)。 -->
    <div class="execution-example-bar"><CoreExecutionControls v-model="model" v-model:thinking-mode="thinking" v-model:permission-preset="permission" v-model:active-mode="mode" v-model:catalog-view="catalog" :model-options="models" :thinking-mode-options="levels" :mode-options="[{ value: 'normal', label: '标准' }, { value: 'review', label: '审阅' }]" :disabled="disabled"><template #after-runtime><CoreWorkspaceMenu :active-id="workspace" :disabled="disabled" :options="[{ id: 'workspace-a', label: '示例电脑', platform: 'windows', online: true }, { id: 'workspace-b', label: '示例远程环境', platform: 'windows', online: false }]" @select="workspace = $event" /></template></CoreExecutionControls></div>
    <span>本地模型：{{ model }} · 本地权限：{{ permission }} · 本地思考：{{ thinking }} · 本地模式：{{ mode }} · 本地环境：{{ workspace }}</span>
  </div>
</template>

<style scoped>
.execution-example { width: 100%; display: grid; gap: var(--space-3); }
.execution-example-bar { padding: var(--space-3); border-radius: var(--radius); background: var(--theme-composer-background); }
</style>
