<script setup lang="ts">
import { ref } from 'vue'
import { copyText } from '@/helpers/clipboard'
import { t } from '@/i18n'

const props = defineProps<{ source: string; title: string; variant: string }>()
const draft = ref(props.source), editing = ref(false), status = ref('')
// user:“总的来说就是样式块”+(成稿块支持本地编辑和复制，不将展示按钮当作发信或后台授权)。
async function copy() {
  try { await copyText(draft.value); status.value = t('已复制') }
  catch { status.value = t('复制失败') }
}
</script>
<template>
  <section class="writing-block" :aria-label="title">
    <header><strong>{{ title }}</strong><div class="writing-actions"><button type="button" data-writing-edit :aria-pressed="editing" @click="editing = !editing">{{ editing ? t('预览') : t('编辑') }}</button><button type="button" data-writing-copy @click="copy">{{ t('复制') }}</button></div></header>
    <textarea v-if="editing" v-model="draft" :aria-label="t('编辑成稿')" spellcheck="false" />
    <slot v-else :content="draft" />
    <span v-if="status" class="writing-status" role="status">{{ status }}</span>
  </section>
</template>
<style scoped>
.writing-block { --text: var(--theme-main-text); padding: var(--space-3); background: var(--theme-main-soft-background); color: var(--text); border: 1px solid var(--theme-main-border); border-radius: var(--radius); }
header, .writing-actions { display: flex; align-items: center; gap: var(--space-2); }
header { justify-content: space-between; margin-bottom: var(--space-2); }
button { color: var(--theme-control-text); background: var(--theme-control-background); border: 0; border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); }
button:hover { filter: brightness(.94); }
textarea { width: 100%; min-height: 160px; resize: vertical; font: inherit; color: var(--theme-composer-text); background: var(--theme-composer-background); border: 0; border-radius: var(--radius-sm); padding: var(--space-2); outline: none; }
textarea:focus-visible { outline: none; }
.writing-status { color: color-mix(in srgb, var(--text) 65%, transparent); }
</style>
