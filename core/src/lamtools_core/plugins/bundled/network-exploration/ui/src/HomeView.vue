<script setup>
// user:“首页重做，放三个块和一个 bar，bar 写数值，三个块分别是加速代理下载的快捷操作”+(首页只保留实时数值条与三个可直接操作的快捷块)。
import { computed, onMounted, ref } from "vue";
import {
  Power,
  ArrowUpRight,
  ArrowDown,
  ArrowUp,
  Activity,
  Database,
  Gauge,
  Globe,
  Download,
  Zap,
} from "lucide-vue-next";
import {
  bytes,
  filenameFromUrl,
  nodeLabel,
  primaryNode,
  rate,
} from "./session.mjs";
const props = defineProps({ session: Object });
const emit = defineEmits(["navigate"]);
const draft = ref("");
onMounted(() => props.session.loadTasks());
const active = computed(() => Boolean(props.session.accelerated));
const download = computed(() =>
  Number(props.session.state?.traffic?.download || 0),
);
const upload = computed(() =>
  Number(props.session.state?.traffic?.upload || 0),
);
const total = computed(
  () =>
    Number(props.session.state?.traffic?.received || 0) +
    Number(props.session.state?.traffic?.sent || 0),
);
const saved = computed(() =>
  Boolean(props.session.state?.proxy?.config_saved),
);
const proxyRunning = computed(() =>
  Boolean(props.session.state?.proxy?.running),
);
const node = computed(() => primaryNode(props.session.proxy));
const nodeText = computed(() =>
  node.value
    ? nodeLabel(node.value)
    : proxyRunning.value
      ? "正在读取线路"
      : "尚未连接",
);
const delay = computed(() =>
  Number(
    props.session.proxy?.proxies?.[node.value]?.history?.at(-1)?.delay || 0,
  ),
);
const activeCount = computed(
  () =>
    props.session.tasks.filter(
      (task) => !["complete", "removed"].includes(task.status),
    ).length,
);
const totalSpeed = computed(() =>
  props.session.tasks.reduce(
    (sum, task) => sum + (Number(task.downloadSpeed) || 0),
    0,
  ),
);
const accelerationLabel = computed(() =>
  props.session.busy === "proxy.start"
    ? "正在准备线路…"
    : props.session.busy === "accelerator.start"
      ? "正在准备…"
      : props.session.busy === "system.apply"
        ? "正在开启…"
        : active.value
          ? "停止加速"
          : "一键加速",
);
const proxyLabel = computed(() =>
  props.session.busy === "proxy.start"
    ? "连接中…"
    : props.session.busy === "proxy.stop"
      ? "关闭中…"
      : proxyRunning.value
        ? "关闭代理"
        : saved.value
          ? "开启代理"
          : "添加订阅",
);
async function toggleAcceleration() {
  await props.session.toggleAcceleration();
}
async function toggleProxy() {
  if (!saved.value) {
    emit("navigate", "proxy");
    return;
  }
  await props.session.toggleProxy();
}
async function startDownload() {
  const url = draft.value.trim();
  const filename = filenameFromUrl(url);
  if (!filename) {
    props.session.error = "请输入有效的下载链接";
    return;
  }
  const result = await props.session.run(
    "transfer.add",
    { url, filename, connections: 8 },
    "已开始下载",
  );
  if (!result) return;
  draft.value = "";
  await props.session.loadTasks();
}
</script>
<template>
  <div class="nx-home">
    <section class="nx-stat-bar" data-stat-bar aria-label="实时网络数据">
      <div class="nx-stat" data-stat="download">
        <span><ArrowDown :size="13" />实时下载</span>
        <strong>{{ rate(download) }}</strong>
      </div>
      <div class="nx-stat" data-stat="upload">
        <span><ArrowUp :size="13" />实时上传</span>
        <strong>{{ rate(upload) }}</strong>
      </div>
      <div class="nx-stat" data-stat="total">
        <span><Database :size="13" />累计流量</span>
        <strong>{{ bytes(total) }}</strong>
      </div>
      <div class="nx-stat" data-stat="delay">
        <span><Gauge :size="13" />线路延迟</span>
        <strong>{{ delay ? `${delay} ms` : "—" }}</strong>
      </div>
    </section>

    <div class="nx-home-grid">
      <section
        class="nx-quick-card"
        :class="{ 'is-on': active }"
        data-home-block="acceleration"
      >
        <header class="nx-quick-head">
          <span class="nx-quick-icon"><Zap :size="19" /></span>
          <div class="nx-quick-title">
            <h2>加速</h2>
            <p>本机加速</p>
          </div>
          <span class="nx-quick-state" :class="{ 'is-live': active }">{{
            active ? "运行中" : "未加速"
          }}</span>
        </header>
        <div class="nx-quick-main">
          <strong>{{ active ? "常用站点直连" : "无需订阅" }}</strong>
          <p>
            {{
              active
                ? proxyRunning
                  ? "本机直连 · 线路兜底已就绪"
                  : "DoH 选路，失败时按系统解析"
                : "有订阅会自动准备线路兜底"
            }}
          </p>
        </div>
        <div class="nx-quick-actions">
          <button
            class="nx-button"
            :class="active ? 'nx-secondary' : 'nx-primary'"
            :aria-pressed="active"
            :disabled="Boolean(session.busy) || !session.systemProxyReady"
            data-acceleration
            @click="toggleAcceleration"
          >
            <Power :size="15" />{{ accelerationLabel }}
          </button>
          <button
            class="nx-button nx-quiet nx-quick-link"
            data-home-open="overview"
            @click="emit('navigate', 'overview')"
          >
            详情<ArrowUpRight :size="13" />
          </button>
        </div>
      </section>

      <section
        class="nx-quick-card"
        :class="{ 'is-on': proxyRunning }"
        data-home-block="proxy"
      >
        <header class="nx-quick-head">
          <span class="nx-quick-icon"><Globe :size="19" /></span>
          <div class="nx-quick-title">
            <h2>代理</h2>
            <p>订阅线路</p>
          </div>
          <span class="nx-quick-state" :class="{ 'is-live': proxyRunning }">{{
            proxyRunning ? "已连接" : saved ? "待连接" : "未配置"
          }}</span>
        </header>
        <div class="nx-quick-main">
          <strong>{{ nodeText }}</strong>
          <p>
            {{
              proxyRunning && delay
                ? `${delay} ms · 当前线路`
                : saved
                  ? "开启后加载订阅里的节点"
                  : "先去代理页添加订阅"
            }}
          </p>
        </div>
        <div class="nx-quick-actions">
          <button
            class="nx-button"
            :class="proxyRunning ? 'nx-secondary' : 'nx-primary'"
            :aria-pressed="proxyRunning"
            :disabled="Boolean(session.busy)"
            data-home-proxy
            @click="toggleProxy"
          >
            <Power :size="15" />{{ proxyLabel }}
          </button>
          <button
            class="nx-button nx-quiet nx-quick-link"
            data-home-open="proxy"
            @click="emit('navigate', 'proxy')"
          >
            选线路<ArrowUpRight :size="13" />
          </button>
        </div>
      </section>

      <section
        class="nx-quick-card"
        :class="{ 'is-on': activeCount > 0 }"
        data-home-block="transfer"
      >
        <header class="nx-quick-head">
          <span class="nx-quick-icon"><Download :size="19" /></span>
          <div class="nx-quick-title">
            <h2>下载</h2>
            <p>快速取回文件</p>
          </div>
          <span
            class="nx-quick-state"
            :class="{ 'is-live': activeCount > 0 }"
            >{{ activeCount ? "进行中" : "空闲" }}</span
          >
        </header>
        <div class="nx-quick-main">
          <strong>{{
            activeCount ? `${activeCount} 个任务` : "没有进行中的下载"
          }}</strong>
          <p>
            {{
              activeCount
                ? `${rate(totalSpeed)} 总速度`
                : "粘贴链接即可开始，默认 8 连接"
            }}
          </p>
        </div>
        <div class="nx-quick-actions nx-quick-actions--stack">
          <form
            class="nx-home-download"
            data-home-download
            @submit.prevent="startDownload"
          >
            <input
              v-model="draft"
              class="nx-input"
              aria-label="下载链接"
              placeholder="粘贴下载链接"
              required
            /><button
              class="nx-button nx-primary"
              :disabled="Boolean(session.busy) || !draft.trim()"
              aria-label="开始下载"
            >
              <Download :size="15" />
            </button>
          </form>
          <button
            class="nx-button nx-quiet nx-quick-link"
            data-home-open="transfer"
            @click="emit('navigate', 'transfer')"
          >
            打开下载页<ArrowUpRight :size="13" />
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
