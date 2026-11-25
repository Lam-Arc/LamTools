<script setup>
// user:“用户最关心最常用的东西有没有放在首页？比如下载/加速/代理。这三样是最关键”+(首页就是三个操作台：下载、加速、代理，全部可直接操作)。
// user:“当把界面上的所有文字都去掉的时候，用户还能不能够猜到应该怎么做”+(每个操作台都靠形状与状态自解释：输入框+箭头=下载，开关=开关，地球+名字+下拉箭头=选线路)。
import { computed, ref } from "vue";
import { Download, Zap, Globe, ChevronRight, Plus, Wifi, Router } from "lucide-vue-next";
import UiSelect from "../../../../../../../ui/src/components/UiSelect.vue";
import SundaySwitch from "../../../../../../../ui/src/components/SundaySwitch.vue";
import { rate, nodeLabel } from "./session.mjs";
const props = defineProps({ session: Object });
const emit = defineEmits(["navigate"]);
const draft = ref("");

const active = computed(() => Boolean(props.session.accelerated));
const proxyRunning = computed(() => Boolean(props.session.state?.proxy?.running));
const saved = computed(() => Boolean(props.session.state?.proxy?.config_saved));
const defaultDir = computed(() => props.session.state?.download_default || "读取中");

// 代理：和快捷面板一致，取第一个可选的 Selector 分组。
const groups = computed(() =>
  Object.entries(props.session.proxy?.proxies || {}).filter(
    ([name, node]) => name !== "GLOBAL" && Array.isArray(node.all) && node.type === "Selector",
  ),
);
const group = computed(() => groups.value[0] || null);
const nodes = computed(() => group.value?.[1]?.all || []);
const currentNode = computed(() => group.value?.[1]?.now || "");
const nodeOptions = computed(() =>
  nodes.value.map((name) => ({ value: name, label: nodeLabel(name) })),
);
const delay = computed(() => Number(props.session.proxy?.proxies?.[currentNode.value]?.history?.at(-1)?.delay || 0));
async function chooseNode(name) {
  if (!name || !group.value || name === currentNode.value) return;
  await props.session.selectNode(group.value[0], name);
}

const tasks = computed(() => props.session.tasks || []);
const activeTasks = computed(() => tasks.value.filter((t) => !["complete", "removed"].includes(t.status)));
const shownTasks = computed(() => activeTasks.value.slice(0, 3));
const totalSpeed = computed(() => tasks.value.reduce((sum, t) => sum + (Number(t.downloadSpeed) || 0), 0));

const primary = computed(() => (props.session.interfaces || [])[0] || null);
const localAddress = computed(() => (primary.value?.ipv4 || [])[0] || "");
const gateway = computed(() => (primary.value?.gateway || [])[0] || "");
const reachability = computed(() => {
  if (!primary.value) return { text: "正在读取网卡", tone: "" };
  if (!localAddress.value) return { text: "没有拿到地址", tone: "warn" };
  if (!gateway.value) return { text: "没有默认网关", tone: "warn" };
  return { text: "已连接", tone: "ok" };
});
const lastReport = computed(() => (props.session.state?.reports || []).at(-1) || null);

const STATE_LABELS = {
  waiting: "等待中", paused: "已暂停", recoverable: "待恢复", error: "下载失败", removed: "已取消", complete: "已完成",
};
function taskState(status) {
  return STATE_LABELS[status] || "下载中";
}
function progress(task) {
  return Math.min(100, (Number(task.completedLength || 0) / Math.max(1, Number(task.totalLength || 0))) * 100);
}
async function startDownload() {
  const url = draft.value.trim();
  const result = await props.session.run("transfer.add", { url }, "已开始下载");
  if (!result) return;
  draft.value = "";
  await props.session.loadTasks();
}
async function toggleAcceleration() {
  await props.session.toggleAcceleration();
}
function toggleProxy() {
  if (!saved.value) {
    emit("navigate", "proxy");
    return;
  }
  void props.session.toggleProxy();
}
</script>
<template>
  <div class="nx2-page nx2-home">
    <!-- 下载：输入框 + 箭头按钮，去掉文字也知道「在这里放链接然后下载」。 -->
    <section class="nx2-station" data-home-block="transfer">
      <form class="nx2-station-download" data-home-download @submit.prevent="startDownload">
        <span class="nx2-station-icon"><Download :size="18" :stroke-width="1.8" /></span>
        <input
          v-model="draft"
          class="nx2-input nx2-input--lg"
          aria-label="下载链接"
          placeholder="粘贴下载链接，或把链接拖到这里"
          required
        />
        <button class="nx2-btn nx2-btn--primary nx2-btn--lg" aria-label="开始下载" data-home-download-submit :disabled="Boolean(session.busy) || !draft.trim()">
          <Download :size="16" :stroke-width="2" />
        </button>
      </form>
      <div class="nx2-station-foot">
        <span class="nx2-row-hint nx2-ellipsis" :title="defaultDir">保存到 {{ defaultDir }}</span>
        <button class="nx2-link" data-home-open="transfer" @click="emit('navigate', 'transfer')">
          全部任务<template v-if="activeTasks.length">（{{ activeTasks.length }}）</template><ChevronRight :size="12" />
        </button>
      </div>
    </section>

    <div class="nx2-stations">
      <!-- 加速：一个开关，开没开看形状就能判断。 -->
      <section class="nx2-station" data-home-block="acceleration">
        <div class="nx2-station-top">
          <span class="nx2-station-icon" :class="{ 'is-on': active }"><Zap :size="18" :stroke-width="1.8" /></span>
          <span class="nx2-station-title">加速</span>
          <SundaySwitch
            data-acceleration
            label="本机加速"
            :model-value="active"
            :disabled="Boolean(session.busy) || !session.systemProxyReady"
            @update:model-value="toggleAcceleration"
          />
        </div>
        <p class="nx2-station-state">{{ active ? "已开启" : "未开启" }}<template v-if="proxyRunning"> · 线路兜底就绪</template></p>
      </section>

      <!-- 代理：地球 + 线路名 + 下拉箭头 + 开关。 -->
      <section class="nx2-station" data-home-block="proxy">
        <div class="nx2-station-top">
          <span class="nx2-station-icon" :class="{ 'is-on': proxyRunning }"><Globe :size="18" :stroke-width="1.8" /></span>
          <span class="nx2-station-title">代理</span>
          <SundaySwitch
            v-if="saved"
            data-home-proxy
            label="代理连接"
            :model-value="proxyRunning"
            :disabled="Boolean(session.busy)"
            @update:model-value="toggleProxy"
          />
          <!-- 没有订阅时开关按不动，等于死控件：直接给「添加订阅」这一步。 -->
          <button v-else class="nx2-btn nx2-btn--primary" data-home-proxy @click="emit('navigate', 'proxy')">
            <Plus :size="13" />添加订阅
          </button>
        </div>
        <div v-if="saved && nodes.length" class="nx2-station-select">
          <UiSelect
            :model-value="currentNode"
            :options="nodeOptions"
            :disabled="Boolean(session.busy) || !proxyRunning"
            aria-label="选择线路"
            data-home-node
            :menu-min-width="200"
            @update:model-value="chooseNode"
          />
        </div>
        <p v-else-if="saved" class="nx2-station-state">开启后加载线路</p>
        <p v-if="proxyRunning && delay" class="nx2-station-state">当前线路 {{ delay }} ms</p>
      </section>
    </div>

    <section v-if="shownTasks.length" class="nx2-group">
      <header class="nx2-group-head">
        <h2>正在下载</h2>
        <span class="nx2-row-hint">{{ rate(totalSpeed) }}</span>
      </header>
      <div class="nx2-rows">
        <div v-for="task in shownTasks" :key="task.gid" class="nx2-row nx2-row--task">
          <span class="nx2-row-value nx2-ellipsis" :title="task.filename">{{ task.filename }}</span>
          <span v-if="task.status === 'active'" class="nx2-row-hint">{{ rate(task.downloadSpeed) }}</span>
          <span v-else class="nx2-tag" :class="{ 'is-bad': task.status === 'error' }">{{ taskState(task.status) }}</span>
          <span class="nx2-mini-track"><span :style="{ width: `${progress(task)}%` }" /></span>
        </div>
      </div>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head">
        <h2>网络</h2>
        <span class="nx2-tag" :class="`is-${reachability.tone}`">{{ reachability.text }}</span>
        <button class="nx2-link" data-home-diagnose @click="emit('navigate', 'diagnose')">检查网络<ChevronRight :size="12" /></button>
      </header>
      <div class="nx2-rows" data-network-strip>
        <div class="nx2-row nx2-row--cols">
          <span class="nx2-row-label"><Wifi :size="12" :stroke-width="1.9" />连接</span>
          <span class="nx2-row-value">{{ primary?.name || "读取中" }}</span>
          <span class="nx2-row-hint nx2-mono">{{ localAddress || "无地址" }}</span>
        </div>
        <div class="nx2-row nx2-row--cols">
          <span class="nx2-row-label"><Router :size="12" :stroke-width="1.9" />网关</span>
          <span class="nx2-row-value nx2-mono">{{ gateway || "没有默认网关" }}</span>
          <span class="nx2-row-hint">{{ lastReport ? (lastReport.failures > 0 ? "上次检查有未通过项" : "上次检查通过") : "还没检查过" }}</span>
        </div>
      </div>
    </section>

    <button class="nx2-btn nx2-btn--ghost nx2-wide" data-home-open="devices" @click="emit('navigate', 'devices')">
      我的设备<ChevronRight :size="13" />
    </button>
  </div>
</template>
