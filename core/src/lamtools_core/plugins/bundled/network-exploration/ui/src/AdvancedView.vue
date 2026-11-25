<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络工具复用应用开关，保留原有操作与禁用条件)。
import SundaySwitch from "../../../../../../../ui/src/components/SundaySwitch.vue";
import UiSelect from "../../../../../../../ui/src/components/UiSelect.vue";
import { ref } from "vue";
import {
  Clock,
  Plus,
  X,
  Play,
  Monitor,
  FileDown,
  ChevronDown,
  Check,
} from "lucide-vue-next";
import { dateLabel } from "./session.mjs";
const props = defineProps({ session: Object });
const creating = ref(false),
  target = ref("github.com"),
  interval = ref("30"),
  devices = ref(null),
  sample = ref(String(props.session.state?.settings?.sample_seconds || 5)),
  savingSample = ref(false);
// user:“确保视觉、功能和交互不退化”+(选择采样间隔时保持原有保存请求与版本)。
const intervalOptions = [{ value: '15', label: '每 15 分钟' }, { value: '30', label: '每 30 分钟' }, { value: '60', label: '每小时' }, { value: '360', label: '每 6 小时' }];
const sampleOptions = [2, 5, 10, 30].map(value => ({ value: String(value), label: `每 ${value} 秒` }));
async function setSample(value) {
  // user:“确保视觉、功能和交互不退化”+(成功后才显示新频率；取消或失败可重试)。
  if (savingSample.value || value === sample.value) return;
  savingSample.value = true;
  try {
    const result = await props.session.run('settings.update', { revision: props.session.state.revision, settings: { sample_seconds: Number(value) } }, '更新频率已保存');
    if (result && !result.cancelled) sample.value = value;
  } finally {
    savingSample.value = false;
  }
}
async function save(rows) {
  return props.session.run(
    "automation.save",
    { revision: props.session.state.revision, automations: rows },
    "定时检查已更新",
  );
}
async function add() {
  let domain = target.value.trim();
  try {
    if (domain.includes("://")) domain = new URL(domain).hostname;
  } catch {
    props.session.error = "请输入有效的网址";
    return;
  }
  const result = await save([
    ...(props.session.state.automations || []),
    {
      target: domain,
      action: "diagnose",
      enabled: true,
      interval_minutes: Number(interval.value),
    },
  ]);
  if (result && !result.cancelled) creating.value = false;
}
async function toggle(index) {
  const rows = props.session.state.automations.map((row, i) => ({
    ...row,
    ...(i === index ? { enabled: !row.enabled } : {}),
  }));
  await save(rows);
}
async function remove(index) {
  await save(props.session.state.automations.filter((_, i) => i !== index));
}
async function preview(index) {
  const result = await props.session.run("automation.run", {
    index,
    dry_run: true,
  });
  if (result)
    props.session.notice = `这条计划会检查 ${result.would_execute?.target || ""}，不会修改网络设置。`;
}
async function exportReports() {
  const result = await props.session.run("export");
  if (!result) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "network-reports.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function loadDevices() {
  devices.value = await props.session.read("lan");
}
</script>
<template>
  <div class="nx2-page">
    <section class="nx2-group">
      <header class="nx2-group-head">
        <h2>定时检查</h2>
        <button class="nx2-btn nx2-btn--ghost" data-add-schedule @click="creating = !creating">{{ creating ? "收起" : "新增计划" }}</button>
      </header>
      <form v-if="creating" class="nx2-composer nx2-composer--inline" @submit.prevent="add">
        <input v-model="target" class="nx2-input" placeholder="检查哪个网站" aria-label="定时检查的网站" />
        <UiSelect v-model="interval" :options="intervalOptions" aria-label="检查间隔" data-network-interval :menu-min-width="140" />
        <button class="nx2-btn nx2-btn--primary" :disabled="Boolean(session.busy)">添加计划</button>
      </form>
      <div v-if="session.state?.automations?.length" class="nx2-rows">
        <div v-for="(row, index) in session.state.automations" :key="index" class="nx2-row nx2-row--cols" data-schedule-row>
          <SundaySwitch size="sm" :label="`${row.target} 定时检查`" :model-value="row.enabled" :disabled="Boolean(session.busy)" @update:model-value="toggle(index)" />
          <span class="nx2-row-value">{{ row.target }}</span>
          <span class="nx2-row-hint">每 {{ row.interval_minutes }} 分钟</span>
          <span class="nx2-actions">
            <button class="nx2-link" :disabled="Boolean(session.busy)" @click="preview(index)"><Play :size="12" />试运行</button>
            <button class="nx2-link nx2-bad" :disabled="Boolean(session.busy)" aria-label="删除定时检查" @click="remove(index)"><X :size="12" /></button>
          </span>
        </div>
      </div>
      <p v-else class="nx2-empty-line">还没有定时检查。它只做只读诊断，不会改网络设置。</p>
    </section>

    <!-- 局域网设备本来属于「互联」；这里只保留按需读取的一眼核对，不重复做一整套页面。 -->
    <section class="nx2-group">
      <header class="nx2-group-head">
        <h2>局域网设备</h2>
        <span class="nx2-row-hint">系统邻居缓存，只读</span>
        <button class="nx2-btn nx2-btn--ghost" @click="loadDevices"><Monitor :size="13" />查看设备</button>
      </header>
      <table v-if="devices?.devices?.length" class="nx2-table" data-device-table>
        <thead><tr><th>地址</th><th>物理地址</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="row in devices.devices" :key="row.IPAddress">
            <td class="nx2-mono">{{ row.IPAddress }}</td>
            <td class="nx2-mono nx2-dim">{{ row.LinkLayerAddress || "—" }}</td>
            <td>{{ row.state || "未知" }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="nx2-empty-line">点「查看设备」读取系统邻居缓存（不代表都在线）。</p>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head"><h2>更新频率</h2></header>
      <div class="nx2-row nx2-row--cols">
        <span class="nx2-row-label">网速采样</span>
        <UiSelect :model-value="sample" :options="sampleOptions" :disabled="Boolean(session.busy) || savingSample" aria-label="网速采样间隔" data-network-sampling :menu-min-width="140" @update:model-value="setSample" />
        <span class="nx2-row-hint">间隔越短数字越及时，开销也越高。</span>
      </div>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head">
        <h2>活动记录</h2>
        <button class="nx2-btn nx2-btn--ghost" @click="exportReports"><FileDown :size="13" />导出</button>
      </header>
      <div v-if="session.state?.events?.length" class="nx2-rows">
        <div v-for="(event, index) in [...session.state.events].reverse().slice(0, 40)" :key="index" class="nx2-row">
          <span class="nx2-row-value">{{ event.message }}</span>
          <span class="nx2-row-hint">{{ dateLabel(event.time) }}</span>
        </div>
      </div>
      <p v-else class="nx2-empty-line">还没有记录。</p>
    </section>
  </div>
</template>
