<template>
  <!-- user:“一次性处理干净 不要留尾巴”+(信任可查看和撤销，不留下不可管理的授权)。 -->
  <section class="permission-section" aria-label="已信任操作">
    <div class="permission-section-heading"><h2>{{ t('已信任操作') }}</h2></div>
    <p>{{ t('每次信任将完全相同操作的等级降低一级，最低为 1 级。撤销后恢复默认等级。') }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!entries.length && !error">{{ t('暂无已信任操作') }}</p>
    <div v-for="entry in entries" :key="entry.key" class="permission-boundary-row">
      <div class="permission-setting-copy"><strong>{{ label(entry.key) }}</strong><span>{{ t('等级') }} {{ entry.level }}</span></div>
      <button type="button" class="btn btn--ghost" :disabled="busy" data-trust-revoke @click="revoke(entry.key)">{{ t('撤销') }}</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { t } from '@/i18n/index.ts'
const props = defineProps<{ requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>> }>()
const entries = ref<Array<{ key: string; level: number }>>([])
const error = ref('')
const busy = ref(false)
function label(key: string): string {
  try { return (JSON.parse(key) as string[]).join(' · ') } catch { return key }
}
async function load(): Promise<void> {
  try {
    const payload = await props.requestRpc('permissions.trust.list', {})
    entries.value = Array.isArray(payload.entries) ? payload.entries as Array<{ key: string; level: number }> : []
    error.value = ''
  } catch (reason) { error.value = String(reason) }
}
async function revoke(key: string): Promise<void> {
  busy.value = true
  try { await props.requestRpc('permissions.trust.revoke', { key }); await load() }
  catch (reason) { error.value = String(reason) }
  finally { busy.value = false }
}
onMounted(load)
</script>
