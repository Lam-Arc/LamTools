<script setup lang="ts">
import { computed, defineAsyncComponent, ref, type Component } from 'vue'
import { BookOpen } from 'lucide-vue-next'
import CoreConfirmDialog from './CoreConfirmDialog.vue'
import '@/styles/app-page.css'
const pages: Record<string, Component> = {
  library: defineAsyncComponent(() => import('./LibraryHomeView.vue')),
  settings: defineAsyncComponent(() => import('./CoreSettings.vue')),
  arrange: defineAsyncComponent(() => import('./CoreArrangeManager.vue')),
  search: defineAsyncComponent(() => import('./SearchShell.vue')),
  plugins: defineAsyncComponent(() => import('./PluginsShell.vue')),
  account: defineAsyncComponent(() => import('./AccountShell.vue')),
  project: defineAsyncComponent(() => import('./CoreProjectSettings.vue')),
}
const props = defineProps<{ page: string; bindings: Record<string, Record<string, any>>; auxiliary?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const instance = ref<{ requestNavigation?: (proceed: () => void) => void; handleBack?: () => boolean; requestSection?: (id: string) => void; hasUnsavedChanges?: () => boolean; savePendingChanges?: () => Promise<boolean>; discardPendingChanges?: () => void } | null>(null)
const pending = ref<(() => void) | null>(null), saving = ref(false), error = ref('')
function requestNavigation(proceed: () => void) {
  if (instance.value?.requestNavigation) instance.value.requestNavigation(proceed)
  else if (instance.value?.hasUnsavedChanges?.()) { pending.value = proceed; error.value = '' }
  else proceed()
}
async function save() {
  saving.value = true; error.value = ''
  try { if (await instance.value?.savePendingChanges?.()) { const proceed = pending.value; pending.value = null; proceed?.() } else error.value = '未能保存，请检查界面中的提示后重试' }
  catch (cause) { error.value = String(cause) } finally { saving.value = false }
}
function discard() { instance.value?.discardPendingChanges?.(); const proceed = pending.value; pending.value = null; proceed?.() }
// user:“可以在分屏开一个库、设置等”+(复用原界面，辅助屏导航留在屏内，不接管主界面左侧栏)。
const bindings = computed(() => {
  const binding = { ...props.bindings[props.page] }
  if (!props.auxiliary) return binding
  delete binding.ref
  delete binding.onHeading
  delete binding.onSectionChange
  delete binding.activeSection
  delete binding.section
  delete binding.initialSection
  return { ...binding, hideNav: false, bandActions: false, onClose: () => emit('close'), onBack: () => emit('close') }
})
defineExpose({ requestNavigation, handleBack: () => instance.value?.handleBack?.() || false })
</script>
<template>
  <!-- user:“专门对小屏或者说分屏状态做一下适配”+(主区与辅助屏共用局部宽度容器，内部页面独立适配)。 -->
  <div class="core-app-page" :class="{ 'core-app-page--auxiliary': auxiliary }">
    <component :is="pages[page as keyof typeof pages]" v-if="pages[page as keyof typeof pages]" ref="instance" v-bind="bindings" />
    <div v-else class="split-empty"><BookOpen :size="24" :stroke-width="1.3" /><span>这个界面暂时无法在分屏中打开</span></div>
    <CoreConfirmDialog :open="Boolean(pending)" title="保存修改？" :error="error" :loading="saving" confirm-label="保存并关闭" discard-label="不保存并关闭" @confirm="save" @discard="discard" @cancel="pending = null" />
  </div>
</template>
