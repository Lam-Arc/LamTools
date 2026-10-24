<template>
  <PluginRegionBlocks
    v-if="regions.length && rpc"
    :regions="regions"
    :request-rpc="rpc"
    :fill="props.replacerOnly && props.region === 'right'"
  />
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'

import PluginRegionBlocks from '@/components/PluginRegionBlocks.vue'
import {
  contributionsFor,
  contributionsRpc,
  ensureContributions,
  type PluginRegionContribution,
  type PluginRpc,
} from '@/plugins/contributions.ts'

export type { PluginRpc }

const props = defineProps<{
  requestRpc?: PluginRpc
  region: string
  /** 只渲染 replace 接管者：常规项改走图标 dock / rail，不再堆叠。 */
  replacerOnly?: boolean
}>()

const rpc = computed(() => props.requestRpc ?? contributionsRpc())

const regions = computed<PluginRegionContribution[]>(() => {
  const all = contributionsFor(props.region)
  return props.replacerOnly ? all.filter((item) => item.replace) : all
})

onMounted(() => {
  const target = rpc.value
  if (target) void ensureContributions(target)
})
</script>
