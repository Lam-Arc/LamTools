<template>
  <PluginRegionBlocks
    v-if="regions.length && rpc"
    :regions="regions"
    :request-rpc="rpc"
  />
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'

import PluginRegionBlocks from './PluginRegionBlocks.vue'
import {
  contributionsFor,
  contributionsRpc,
  ensureContributions,
  type PluginRegionContribution,
  type PluginRpc,
} from '../plugins/contributions'

export type { PluginRpc }

const props = defineProps<{
  requestRpc?: PluginRpc
  region: string
}>()

const rpc = computed(() => props.requestRpc ?? contributionsRpc())

const regions = computed<PluginRegionContribution[]>(() =>
  contributionsFor(props.region),
)

onMounted(() => {
  const target = rpc.value
  if (target) void ensureContributions(target)
})
</script>
