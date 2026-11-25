<script setup>
// user:“整个 easynet 与其相关界面重新设计”+(加速页也改成状态行 + 事实行，不再用大字卡和大标题)。
import { computed } from "vue";
import { Power, ChevronRight } from "lucide-vue-next";
import SundaySwitch from "../../../../../../../ui/src/components/SundaySwitch.vue";
import SpeedChart from "./SpeedChart.vue";
import { dateLabel } from "./session.mjs";
const props = defineProps({ session: Object });
const emit = defineEmits(["navigate", "diagnostic"]);
const active = computed(() => Boolean(props.session.accelerated));
const proxyRunning = computed(() => Boolean(props.session.state?.proxy?.running));
const running = computed(() => Boolean(props.session.state?.proxy?.running && props.session.state?.proxy?.config_saved));
const events = computed(() => [...(props.session.state?.events || [])].reverse().slice(0, 4));
async function oneClick() {
  await props.session.toggleAcceleration();
}
</script>
<template>
  <div class="nx2-page">
    <!-- user:“按照这个思路，其他页面也一样处理一下”+(加速就是开没开：和首页同一个开关、同一种形状，不在这里换成另一种控件)。 -->
    <section class="nx2-station nx-accel-control" data-acceleration-station>
      <div class="nx2-station-top">
        <span class="nx2-station-icon" :class="{ 'is-on': active }"><Power :size="18" :stroke-width="1.8" /></span>
        <span class="nx2-station-title">本机加速<small class="nx2-row-hint">{{ active ? "已开启" : "未开启" }}</small></span>
        <SundaySwitch
          data-acceleration
          label="本机加速"
          :model-value="active"
          :disabled="Boolean(session.busy) || !session.systemProxyReady"
          @update:model-value="oneClick"
        />
      </div>
      <p class="nx2-station-state">
        {{ active
          ? "命中 GitHub、Steam 等常用站点时用 DoH 选 IP 直连，不改 hosts、不装证书。"
          : "不需要订阅。开启后只改系统代理，指向本机加速端口。" }}
      </p>
      <p v-if="session.busy" class="nx2-station-state">
        {{ session.busy === "proxy.start" ? "正在准备线路…" : session.busy === "accelerator.start" ? "正在准备…" : "正在开启…" }}
      </p>
      <p v-else-if="!session.systemProxyReady" class="nx2-station-state nx2-bad">系统代理不可用，先到「代理与线路」检查。</p>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head"><h2>运行方式</h2></header>
      <div class="nx2-rows">
        <div class="nx2-row nx2-row--cols"><span class="nx2-row-label">加速方式</span><span class="nx2-row-value">DoH 选 IP 直连</span><span class="nx2-row-hint">命中常用站点才走加速</span></div>
        <div class="nx2-row nx2-row--cols"><span class="nx2-row-label">系统改动</span><span class="nx2-row-value">仅系统代理</span><span class="nx2-row-hint">不改 DNS、不改 hosts</span></div>
        <div class="nx2-row nx2-row--cols"><span class="nx2-row-label">证书</span><span class="nx2-row-value">不安装</span><span class="nx2-row-hint">TLS 原样透传</span></div>
        <div class="nx2-row nx2-row--cols">
          <span class="nx2-row-label">线路兜底</span>
          <span class="nx2-row-value">{{ proxyRunning ? "已就绪" : "未开启" }}</span>
          <button class="nx2-link" @click="emit('navigate', 'proxy')">去代理页管理<ChevronRight :size="12" /></button>
        </div>
      </div>
    </section>

    <!-- 网速图自己带标题与数值，外面不再套一层重复标题。 -->
    <SpeedChart :history="session.state?.history || []" :traffic="session.state?.traffic" />

    <section class="nx2-group">
      <header class="nx2-group-head"><h2>最近活动</h2><button class="nx2-link" @click="emit('navigate', 'advanced')">查看记录<ChevronRight :size="12" /></button></header>
      <div v-if="events.length" class="nx2-rows">
        <div v-for="(event, index) in events" :key="index" class="nx2-row">
          <span class="nx2-row-value">{{ event.message }}</span>
          <span class="nx2-row-hint">{{ dateLabel(event.time) }}</span>
        </div>
      </div>
      <p v-else class="nx2-empty-line">还没有事件。</p>
    </section>
  </div>
</template>
