<template>
  <div class="library-search">
    <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(资料、记忆与方案共享原生搜索框，保留各页面的标签和查询行为)。 -->
    <Search :size="iconSize ?? 14" :stroke-width="iconStrokeWidth ?? 1.8" :class="iconClass" aria-hidden="true" />
    <input ref="input" v-bind="inputAttrs" v-model="model" :type="type ?? 'search'" :placeholder="placeholder || label" :aria-label="label" />
    <!-- user:“通过参数、变体和组合保留必要差异”+(允许成果库组合清除按钮，保持已有交互)。 -->
    <slot />
  </div>
</template>
<script setup lang="ts">
import { Search } from 'lucide-vue-next'
import { ref } from 'vue'
defineProps<{ label: string; placeholder?: string; type?: 'text' | 'search'; iconSize?: number; iconClass?: string; iconStrokeWidth?: number; inputAttrs?: Record<string, string> }>()
// user:“通过参数、变体和组合保留必要差异”+(设置页保留原有 trim 查询行为与图标描边)。
const [model, modifiers] = defineModel<string, 'trim'>({ required: true, set: value => modifiers.trim ? value.trim() : value })
// user:“通过参数、变体和组合保留必要差异”+(插件搜索快捷键与清除操作可以将焦点还给输入框)。
const input = ref<HTMLInputElement | null>(null)
defineExpose({ focus: () => input.value?.focus() })
</script>
