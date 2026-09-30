<template>
  <!-- 桌面：动作送到顶部条的右侧，与标题同一行；手机没有顶部条，就地渲染。 -->
  <Teleport v-if="toBand" defer to="#full-area-band-actions">
    <div class="full-area-actions"><slot /></div>
  </Teleport>
  <div v-else class="full-area-actions"><slot /></div>
</template>

<script setup lang="ts">
/**
 * FullAreaActions — the action group of a full-area view (搜索 / 资料库 /
 * 长期安排 / 设置 / 插件 / 账号).
 *
 * One row, one axis: on desktop the actions ride in the header band next to the
 * view title; on phones there is no band, so they render where the view's own
 * header sits. Views keep one markup for both.
 */
defineProps<{
  /** Whether a header band exists to send the actions into (desktop). */
  toBand?: boolean
}>()
</script>
