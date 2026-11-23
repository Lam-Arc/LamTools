<script setup lang="ts">
import { ref } from 'vue'
import FirstRunChecklist from '@/components/FirstRunChecklist.vue'

// user:“参数调整、变体对比”+(各步骤和按钮只修改展厅内存，不改新手引导状态)。
const provider = ref(false), project = ref(false), session = ref(false), sent = ref(false), visible = ref(true), result = ref('')
</script>

<template>
  <div class="first-run-preview">
    <div class="first-run-preview__controls">
      <label><input v-model="provider" type="checkbox" class="sunday-checkbox" />已配置模型</label>
      <label><input v-model="project" type="checkbox" class="sunday-checkbox" />已有项目</label>
      <label><input v-model="session" type="checkbox" class="sunday-checkbox" />已有会话</label>
      <label><input v-model="sent" type="checkbox" class="sunday-checkbox" />已发送第一条消息</label>
      <button type="button" class="btn btn--secondary" @click="visible = true">显示清单</button>
    </div>
    <FirstRunChecklist :visible="visible" :has-provider="provider" :has-project="project" :has-session="session" :first-message-sent="sent" @action="result = '点击引导'" @dismiss="visible = false" @finished="visible = false" @pick-example="result = $event" />
    <span v-if="result">本地选择：{{ result }}</span>
  </div>
</template>

<style scoped>
.first-run-preview { display: grid; gap: var(--space-3); width: 100%; }
.first-run-preview__controls { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
</style>
