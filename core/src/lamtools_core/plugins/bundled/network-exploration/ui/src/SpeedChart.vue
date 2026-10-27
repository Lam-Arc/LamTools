<script setup>
// user:“示例：不必照抄，只是方向”+(网速趋势作为主要图形，只绘制真实采样，空数据不伪造曲线)。
import { computed, useId } from "vue";
import { ArrowDown, ArrowUp, Activity } from "lucide-vue-next";
import { rate, bytes } from "./session.mjs";
const props = defineProps({
  history: { default: () => [] },
  traffic: { default: null },
  compact: Boolean,
});
const gradient = `nx-speed-${useId().replace(/:/g, "")}`;
const maximum = computed(() =>
  Math.max(
    1024,
    ...props.history.flatMap((row) => [
      Number(row.download || 0),
      Number(row.upload || 0),
    ]),
  ),
);
function line(key) {
  const rows = props.history;
  if (rows.length < 2) return "";
  return rows
    .map(
      (row, index) =>
        `${index ? "L" : "M"}${((index / (rows.length - 1)) * 640).toFixed(2)},${(154 - (Number(row[key] || 0) / maximum.value) * 138).toFixed(2)}`,
    )
    .join(" ");
}
const download = computed(() => line("download")),
  upload = computed(() => line("upload"));
const area = computed(() =>
  download.value ? `${download.value} L640,164 L0,164 Z` : "",
);
</script>
<template>
  <section class="nx-panel nx-speed" data-network-chart>
    <div class="nx-panel-heading">
      <h2><Activity :size="17" />实时网速</h2>
      <span class="nx-subtle">系统接口</span>
    </div>
    <div class="nx-speed-values">
      <span
        ><ArrowDown :size="17" /><strong>{{ rate(traffic?.download) }}</strong
        ><small>下载</small></span
      ><span
        ><ArrowUp :size="17" /><strong>{{ rate(traffic?.upload) }}</strong
        ><small>上传</small></span
      >
    </div>
    <div class="nx-plot">
      <svg
        v-if="history.length > 1"
        viewBox="0 0 640 164"
        preserveAspectRatio="none"
        role="img"
        aria-label="实时下载和上传速度趋势"
      >
        <defs>
          <linearGradient :id="gradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stop-color="currentColor" stop-opacity=".18" />
            <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
          </linearGradient>
        </defs>
        <path
          v-for="y in [26, 72, 118, 163]"
          :key="y"
          :d="`M0,${y}H640`"
          class="nx-chart-grid"
        />
        <path
          :d="area"
          :style="{ fill: `url(#${gradient})` }"
          class="nx-chart-area"
        />
        <path :d="upload" class="nx-chart-upload" />
        <path :d="download" class="nx-chart-download" />
      </svg>
      <div v-else class="nx-chart-wait">
        <Activity :size="22" /><span>正在收集网速变化</span
        ><small>新的采样会自动显示在这里</small>
      </div>
    </div>
    <div class="nx-chart-axis">
      <span>{{ history.length > 1 ? "较早" : "等待采样" }}</span
      ><span v-if="history.length > 1">最高 {{ bytes(maximum) }}/s</span
      ><span>现在</span>
    </div>
  </section>
</template>
