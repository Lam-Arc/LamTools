<script setup lang="ts">
import { useRouter } from 'vue-router'
import { CoreArrangeManager } from '@lamtools/ui'
import { listArrangeJobs, updateArrangeJob } from '../api/core'

const router = useRouter()
</script>

<template>
  <CoreArrangeManager
    :list-jobs="listArrangeJobs"
    :update-job="updateArrangeJob"
    @back="router.push('/')"
  />
</template>
