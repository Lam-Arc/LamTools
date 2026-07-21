<script setup lang="ts">
import { useRouter } from 'vue-router'
import { CoreArrangeManager, listArrangeJobs, updateArrangeJob } from '@lamtools/ui'

const router = useRouter()
</script>

<template>
  <CoreArrangeManager
    :list-jobs="listArrangeJobs"
    :update-job="updateArrangeJob"
    @back="router.push('/')"
  />
</template>
