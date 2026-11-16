<template>
  <div class="cu-cursor" :style="{ left: `${x}px`, top: `${y}px` }" aria-hidden="true">
    <span class="cu-cursor-color" />
    <span class="cu-cursor-core" />
  </div>
</template>

<script setup lang="ts">
/**
 * user:“这个彩是怎么做的？”+“同角度，转起来”+
 * (彩层不再用固定在图形上的线性渐变，改成锥形渐变，角度取 --cu-angle；
 *  这个变量由页面根节点驱动，屏幕边框和光标读到的是同一个值，所以永远同相。)
 */
withDefaults(
  defineProps<{
    /** 相对覆盖层的 CSS 像素坐标，箭尖落在这里。 */
    x?: number
    y?: number
  }>(),
  {
    x: 0,
    y: 0,
  },
)
</script>

<style scoped>
.cu-cursor {
  position: fixed;
  width: 24px;
  height: 28px;
  pointer-events: none;
  /* 移动时滑过去而不是瞬移；底部一点点投影让黑底从浅色背景里浮出来。 */
  transition: left 0.16s ease-out, top 0.16s ease-out;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5));
}

.cu-cursor-color,
.cu-cursor-core {
  position: absolute;
  inset: 0;
  display: block;
}

/* user:“同角度”+(和屏幕边框共用 --cu-angle，色相绕一圈的节奏一致。) */
.cu-cursor-color {
  background: conic-gradient(
    from var(--cu-angle, 0deg),
    #7b62c9,
    #2f8f84,
    #a4566d,
    #4f68b8,
    #7b62c9
  );
  clip-path: path(
    'M1.52 2.93 Q1 1 2.64 2.15 L20.66 14.77 Q22.3 15.91 20.38 16.48 L15.21 17.99 Q13.29 18.56 12.11 20.17 L8.91 24.5 Q7.73 26.11 7.21 24.18 L1.52 2.93 Z'
  );
}

/* 黑芯：同形状绕重心缩到 64%，两层完全相似。 */
.cu-cursor-core {
  background: #0a0a0c;
  clip-path: path(
    'M4.97 7.44 Q4.63 6.18 5.69 6.93 L17.19 14.98 Q18.26 15.73 17.01 16.09 L13.74 17.05 Q12.5 17.42 11.73 18.47 L9.71 21.21 Q8.94 22.26 8.6 21 L4.97 7.44 Z'
  );
}

@media (prefers-reduced-motion: reduce) {
  .cu-cursor {
    transition: none;
  }
}
</style>
