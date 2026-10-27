<script setup>
// user:“样式示例：不必照抄，只是方向”+(流量统计用真实累计计数绘制比例，不生成假数据)。
import { computed } from "vue";
import { PieChart, ArrowDown, ArrowUp } from "lucide-vue-next";
import { bytes } from "./session.mjs";
const props = defineProps({ traffic: { default: null } });
const download = computed(() => Number(props.traffic?.received || 0)),
  upload = computed(() => Number(props.traffic?.sent || 0)),
  total = computed(() => download.value + upload.value),
  downloadPercent = computed(() =>
    total.value > 0 ? Math.round((download.value / total.value) * 100) : 0,
  );
const donut = computed(() => ({
  background: `conic-gradient(var(--nx-accent) 0 ${downloadPercent.value}%, #3a4640 ${downloadPercent.value}% 100%)`,
}));
</script>
<template>
  <section class="nx-panel nx-traffic-card">
    <div class="nx-panel-heading">
      <h2><PieChart :size="17" />流量统计</h2>
    </div>
    <div class="nx-donut-row">
      <div class="nx-donut" :style="donut" role="img" :aria-label="`下载占 ${downloadPercent}%`">
        <span>{{ downloadPercent }}%</span>
      </div>
      <div class="nx-traffic-legend">
        <div>
          <span class="nx-legend-down"><ArrowDown :size="13" />下载</span
          ><strong>{{ bytes(download) }}</strong>
        </div>
        <div>
          <span class="nx-legend-up"><ArrowUp :size="13" />上传</span
          ><strong>{{ bytes(upload) }}</strong>
        </div>
      </div>
    </div>
    <p class="nx-help">系统接口累计计数</p>
  </section>
</template>
