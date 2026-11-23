<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { LoaderCircle } from 'lucide-vue-next'
import UiSelect from '@/components/UiSelect.vue'
import SundayProgress from '@/components/SundayProgress.vue'

// user:“做”+(从一个展项体验生产浮层、入场和等待；开关只模拟这份展厅的共享 CSS 动效)。
const reduced = ref(false)
const replay = ref(0)
const choice = ref('first')
const choices = [{ value: 'first', label: '第一项' }, { value: 'second', label: '第二项' }]

watch(reduced, value => document.documentElement.classList.toggle('sunday-motion-preview-reduced', value))
onBeforeUnmount(() => document.documentElement.classList.remove('sunday-motion-preview-reduced'))
</script>

<template>
  <div class="motion-preview" data-motion-preview>
    <label>
      <input v-model="reduced" type="checkbox" class="sunday-checkbox" aria-label="模拟减少动效" />
      模拟减少动效（共享动作）
    </label>
    <div class="motion-options">
      <section class="sunday-page-panel motion-sample">
        <h3>浮层开合</h3>
        <UiSelect v-model="choice" :options="choices" aria-label="示例浮层" :menu-min-width="0" />
      </section>
      <section class="sunday-page-panel motion-sample">
        <h3>列表与消息入场</h3>
        <button type="button" class="btn btn--secondary btn--sm" @click="replay++">重播入场</button>
        <div :key="replay" class="sunday-motion-row motion-sample-row" data-motion-row>新内容就绪</div>
      </section>
      <section class="sunday-page-panel motion-sample">
        <h3>等待反馈</h3>
        <div class="motion-sample-label" role="status">
          <LoaderCircle class="sunday-spin" :size="16" aria-hidden="true" data-motion-spinner />
          正在加载
        </div>
        <SundayProgress indeterminate label="示例任务" value-text="正在处理" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.motion-preview { display: grid; gap: var(--space-3); width: 100%; }
.motion-options { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--space-2); }
.motion-sample { display: grid; align-content: start; gap: var(--space-2); padding: var(--space-3); }
.motion-sample h3 { margin: 0; font-size: 14px; }
.motion-sample .btn { justify-self: start; }
.motion-sample-row { padding: var(--space-2); border-radius: var(--radius-sm); background: var(--theme-main-subtle-background); font-size: 13px; }
.motion-sample-label { display: flex; align-items: center; gap: var(--space-2); font-size: 13px; }
</style>
