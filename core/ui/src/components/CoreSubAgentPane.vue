<!-- Compatibility adapter: the generic workspace now embeds CoreSubAgentView. -->
<script setup lang="ts">
import CoreSubAgentView from './CoreSubAgentView.vue'
import type { CoreSubAgentRun, CoreSubAgentDurableRecord } from '@/types'
import type { LamToolsTransport } from '@/transport'
defineProps<{
  run: CoreSubAgentRun; transport: LamToolsTransport; emptyText?: string; teleportTo?: string
  durableRecord?: CoreSubAgentDurableRecord | null; width?: number | null; memberWaitKnown?: boolean
  runningMemberNames?: string[]; mainRunning?: boolean; memberStatuses?: Record<string, string>
  memberStatusRecords?: Record<string, CoreSubAgentDurableRecord>
}>()
defineOptions({ inheritAttrs: false })
</script>
<template><CoreSubAgentView v-bind="{ ...$props, ...$attrs }" :embedded="false" /></template>
