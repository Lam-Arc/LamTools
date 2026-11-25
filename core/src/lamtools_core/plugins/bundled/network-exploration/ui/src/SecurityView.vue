<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“可交互式网络工具界面，不需要太专业”+(优先选择正在运行的应用，系统修改仍使用宿主审批及恢复接口)。
import { computed, ref } from "vue";
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(应用和限速选择复用共享下拉并保持原有申请行为)。
import UiSelect from "../../../../../../../ui/src/components/UiSelect.vue";
import {
  ShieldCheck,
  ShieldOff,
  RefreshCw,
  Undo2,
  ChevronDown,
  Monitor,
} from "lucide-vue-next";
import { dateLabel } from "./session.mjs";
const props = defineProps({ session: Object });
const choosing = ref(false),
  apps = ref([]),
  selected = ref(""),
  manual = ref(false),
  speed = ref("8000000");
const appOptions = computed(() => apps.value.map(app => ({ value: app.path, label: `${app.process} · ${app.path.split("\\").at(-1)}` })));
const speedOptions = [{ value: '8000000', label: '1 MB/s' }, { value: '40000000', label: '5 MB/s' }, { value: '80000000', label: '10 MB/s' }];
const transactions = computed(() =>
  [...(props.session.state?.transactions || [])].reverse(),
);
async function loadApps() {
  choosing.value = true;
  const result = await props.session.read("connections", {});
  const seen = new Set();
  apps.value = (result?.connections || [])
    .filter((row) => row.path && !seen.has(row.path) && seen.add(row.path))
    .sort((a, b) => (a.process || "").localeCompare(b.process || ""));
}
async function apply(kind) {
  const path = selected.value.trim();
  if (!path) {
    props.session.error = "先选择一个应用";
    return;
  }
  await props.session.run(
    "system.apply",
    {
      kind,
      program: path,
      ...(kind === "qos" ? { bits_per_second: Number(speed.value) } : {}),
    },
    kind === "qos" ? "已设置应用上传限速" : "已创建应用联网限制",
  );
}
function title(row) {
  return (
    {
      proxy: "系统代理",
      dns: "DNS 设置",
      firewall: "应用联网限制",
      qos: "应用上传限速",
    }[row.request?.kind] || "网络设置"
  );
}
function status(value) {
  return (
    {
      applied: "正在生效",
      restored: "已恢复",
      prepared: "待核对",
      recovery_required: "需要恢复",
      external_change: "设置已被外部修改",
      failed: "未生效",
      rolled_back: "已撤回",
    }[value] || value
  );
}
</script>
<template>
  <div class="nx2-page">
    <section class="nx2-group">
      <header class="nx2-group-head">
        <h2>应用联网</h2>
        <button class="nx2-btn" @click="loadApps"><Monitor :size="14" />选择应用</button>
      </header>
      <div v-if="choosing" class="nx2-station">
        <div class="nx2-composer nx2-composer--inline">
          <input v-if="manual" v-model="selected" class="nx2-input" placeholder="应用 .exe 的完整路径" aria-label="应用路径" />
          <UiSelect v-else v-model="selected" :options="appOptions" placeholder="从当前连接的应用中选择" aria-label="选择应用" data-network-application :menu-min-width="220" />
          <button class="nx2-btn nx2-btn--ghost" @click="manual = !manual; selected = ''">{{ manual ? "从列表选择" : "手动输入路径" }}</button>
        </div>
        <div class="nx2-rows">
          <div class="nx2-row nx2-row--cols">
            <span class="nx2-row-label">阻止联网</span>
            <span class="nx2-row-hint">只对这个应用创建出站防火墙规则</span>
            <button class="nx2-btn" :disabled="!selected || Boolean(session.busy)" @click="apply('firewall')"><ShieldOff :size="13" />申请阻止</button>
          </div>
          <div class="nx2-row nx2-row--cols">
            <span class="nx2-row-label">上传限速</span>
            <UiSelect v-model="speed" :options="speedOptions" aria-label="应用上传速度上限" data-network-upload-limit :menu-min-width="140" />
            <button class="nx2-btn" :disabled="!selected || Boolean(session.busy)" @click="apply('qos')">申请限速</button>
          </div>
        </div>
        <p class="nx2-note">这两项可能需要管理员权限，执行前会显示影响范围。</p>
      </div>
      <p v-else class="nx2-empty-line">选择一个应用后，可以只对它阻止联网或限制上传。</p>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head"><h2>网络设置记录</h2><span class="nx2-row-hint">{{ transactions.length }} 条</span></header>
      <div v-if="transactions.length" class="nx2-rows">
        <div v-for="row in transactions" :key="row.id" class="nx2-row nx2-row--cols" data-transaction>
          <span class="nx2-row-value">{{ title(row) }}<small v-if="row.request?.program" class="nx2-row-hint"> · {{ row.request.program.split("\\").at(-1) }}</small></span>
          <span class="nx2-tag" :class="{ 'is-warn': ['external_change', 'recovery_required'].includes(row.status), 'is-ok': row.status === 'applied' }">{{ status(row.status) }}</span>
          <span class="nx2-row-hint">{{ dateLabel(row.time) }}</span>
          <button v-if="row.status === 'applied'" class="nx2-link" :disabled="Boolean(session.busy)" @click="session.run('system.restore', { id: row.id }, '已检查并恢复原设置')">恢复</button>
        </div>
      </div>
      <p v-else class="nx2-empty-line">还没有修改过系统网络设置。</p>
    </section>
  </div>
</template>
