<template>
  <div v-if="windows.length" class="plugin-window-launcher">
    <h4>{{ t("插件窗口") }}</h4>
    <div class="plugin-window-list">
      <button
        v-for="item in windows"
        :key="`${item.plugin}:${item.id}`"
        class="small-btn"
        type="button"
        @click="$emit('open', item)"
      >
        {{ item.title }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { t } from '../i18n/index'

interface PluginWindowEntry {
  plugin: string
  id: string
  title: string
  url: string
  width: number
  height: number
}

// user:“统一与去重”+(补充入口复用宿主已加载的数据及窗口打开行为)。
defineProps<{ windows: PluginWindowEntry[] }>()
defineEmits<{ open: [item: PluginWindowEntry] }>()
</script>

<style scoped>
.plugin-window-launcher {
  display: grid;
  gap: 6px;
}

.plugin-window-launcher h4 {
  margin: 0;
  font-size: 13px;
}

.plugin-window-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
