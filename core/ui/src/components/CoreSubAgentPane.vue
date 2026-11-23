<!-- Compatibility adapter: the generic workspace now embeds CoreSubAgentView. -->
<script setup lang="ts">
import CoreSubAgentView from './CoreSubAgentView.vue'
import type { CoreSubAgentRun, CoreSubAgentDurableRecord } from '@/types'
import type { LamToolsTransport } from '@/transport'
import type { CoreSubAgentRef } from '@/agents/subAgentProjection'
import type { CoreDecisionOption } from '@/appServer/pendingDecisions'
defineProps<{
  run: CoreSubAgentRun; transport: LamToolsTransport; emptyText?: string; teleportTo?: string
  durableRecord?: CoreSubAgentDurableRecord | null; width?: number | null; memberWaitKnown?: boolean
  runningMemberNames?: string[]; mainRunning?: boolean; memberStatuses?: Record<string, string>
  memberStatusRecords?: Record<string, CoreSubAgentDurableRecord>
}>()
// user:“旧测试通过适配器断言 resize/close”+(声明并显式转发子组件事件：
//  只靠 v-bind="$attrs" 时，子组件 emit 不会出现在适配器的 emitted 里；新加的页眉切换也走同一条转发)。
const emit = defineEmits<{
  close: []
  resize: [width: number]
  'decision-select': [payload: { partId: string; option: CoreDecisionOption; response: string }]
  'open-sub-agent': [ref: CoreSubAgentRef]
}>()
defineOptions({ inheritAttrs: false })
</script>
<template>
  <CoreSubAgentView
    v-bind="{ ...$props, ...$attrs }"
    :embedded="false"
    @close="emit('close')"
    @resize="emit('resize', $event)"
    @decision-select="emit('decision-select', $event)"
    @open-sub-agent="emit('open-sub-agent', $event)"
  />
</template>
