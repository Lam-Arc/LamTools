<template>
  <CoreConfirmDialog
    :open="guard.open.value"
    :title="t('保存修改？')"
    :detail="guard.detail.value"
    :error="guard.error.value"
    :loading="guard.busy.value"
    :confirm-label="t('保存并继续')"
    :discard-label="t('丢弃修改')"
    @confirm="guard.saveAndContinue"
    @discard="guard.discardAndContinue"
    @cancel="guard.cancel"
  />
</template>

<script setup lang="ts">
import { t } from '../i18n'
import type { createSettingsDraftGuard } from '../composables/useSettingsDraftGuard'
import CoreConfirmDialog from './CoreConfirmDialog.vue'

defineProps<{ guard: ReturnType<typeof createSettingsDraftGuard> }>()
</script>
