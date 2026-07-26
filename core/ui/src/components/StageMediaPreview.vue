<template>
  <div class="stage-media">
    <video v-if="kind === 'video'" :src="src" controls autoplay class="stage-media-player" />
    <audio v-else :src="src" controls autoplay class="stage-media-audio" />
    <div v-if="error" class="stage-media-error">
      <span>无法加载媒体文件</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  src: string
  kind: 'video' | 'audio'
}>()

const error = ref(false)
</script>

<style scoped>
.stage-media {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}
.stage-media-player {
  max-width: 100%;
  max-height: 100%;
}
.stage-media-audio {
  width: 90%;
  max-width: 500px;
}
.stage-media-error {
  color: #888;
  font-size: 14px;
}
</style>
