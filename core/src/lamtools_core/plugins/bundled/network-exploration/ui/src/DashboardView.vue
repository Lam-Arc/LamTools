<script setup>
// user:“加速页里头不用分什么线路加速…选线路的事儿，去代理里面”+(加速页只做本机加速；订阅和线路全部留在代理页)。
import { computed, ref } from "vue";
import {
  Power,
  ArrowUpRight,
  Link,
  Activity,
  Check,
  ShieldCheck,
} from "lucide-vue-next";
import SpeedChart from "./SpeedChart.vue";
import { dateLabel } from "./session.mjs";
const props = defineProps({ session: Object });
const emit = defineEmits(["navigate", "diagnostic"]);
const target = ref("github.com");
const active = computed(() => Boolean(props.session.accelerated));
async function oneClick() {
  await props.session.toggleAcceleration();
}
async function checkSite() {
  const result = await props.session.diagnose(target.value);
  if (result?.report) emit("diagnostic", result.report);
}
</script>
<template>
  <div class="nx-accel-page">
    <section class="nx-accel-control" :class="{ 'is-on': active }">
      <div class="nx-accel-orb"><Power :size="24" :stroke-width="1.7" /></div>
      <div class="nx-accel-copy">
        <span class="nx-kicker">LOCAL ACCELERATION</span>
        <h2>{{ active ? "本机加速中" : "未加速" }}</h2>
        <p>
          {{
            active
              ? "本机直连：命中 GitHub、Steam 等常用站点时用 DoH 选 IP。"
              : "不需要订阅。点一下，用 DoH 选路直连 GitHub、Steam 等常用站点。"
          }}
        </p>
      </div>
      <button
        class="nx-button nx-large"
        :class="active ? 'nx-secondary' : 'nx-primary'"
        :aria-pressed="active"
        :disabled="Boolean(session.busy) || !session.systemProxyReady"
        data-acceleration
        @click="oneClick"
      >
        <Power :size="17" />{{
          session.busy === "proxy.start"
            ? "正在准备线路…"
            : session.busy === "accelerator.start"
              ? "正在准备…"
              : session.busy === "system.apply"
                ? "正在开启…"
                : active
                  ? "停止加速"
                  : "一键加速"
        }}
      </button>
    </section>

    <div class="nx-accel-grid">
      <SpeedChart
        :history="session.state?.history || []"
        :traffic="session.state?.traffic"
      />
      <section class="nx-panel nx-accel-facts">
        <div class="nx-panel-heading">
          <h2><ShieldCheck :size="17" />运行方式</h2>
        </div>
        <div class="nx-fact">
          <span>加速方式</span><strong>DoH 选 IP 直连</strong>
        </div>
        <div class="nx-fact">
          <span>系统改动</span><strong>仅系统代理</strong>
        </div>
        <div class="nx-fact">
          <span>证书 / hosts</span><strong>不修改</strong>
        </div>
        <div class="nx-fact">
          <span>订阅线路</span
          ><button
            class="nx-button nx-quiet nx-fact-link"
            @click="emit('navigate', 'proxy')"
          >
            去代理页管理<ArrowUpRight :size="13" />
          </button>
        </div>
        <p class="nx-help">
          有订阅时会自动准备线路兜底，但不改系统代理；直连失败的域名会记住并优先走线路。
        </p>
      </section>
    </div>

    <div
      class="nx-accel-lower"
      :class="{ 'nx-single': !session.state?.events?.length }"
    >
      <section class="nx-panel nx-site-check">
        <div class="nx-panel-heading">
          <h2><Link :size="17" />检查网站访问</h2>
        </div>
        <form class="nx-inline-form" @submit.prevent="checkSite">
          <input
            v-model="target"
            class="nx-input"
            aria-label="要检查的网站"
            placeholder="输入网址，例如 github.com"
            required
          /><button
            class="nx-button nx-secondary"
            :disabled="Boolean(session.busy)"
          >
            <Activity :size="15" />{{
              session.busy === "diagnose" ? "检查中…" : "检查一下"
            }}
          </button>
        </form>
        <div class="nx-site-shortcuts">
          <span>常用网站</span
          ><button
            v-for="site in ['github.com', 'huggingface.co', 'google.com']"
            :key="site"
            class="nx-button nx-quiet"
            @click="target = site"
          >
            {{ site }}
          </button>
        </div>
      </section>
      <section v-if="session.state?.events?.length" class="nx-panel nx-recent">
        <div class="nx-section-heading">
          <h2>最近活动</h2>
          <button
            class="nx-button nx-quiet"
            @click="emit('navigate', 'advanced')"
          >
            查看记录<ArrowUpRight :size="13" />
          </button>
        </div>
        <div
          v-for="(event, index) in [...session.state.events]
            .reverse()
            .slice(0, 3)"
          :key="index"
          class="nx-event"
        >
          <Check :size="14" /><span>{{ event.message }}</span
          ><time>{{ dateLabel(event.time) }}</time>
        </div>
      </section>
    </div>
  </div>
</template>
