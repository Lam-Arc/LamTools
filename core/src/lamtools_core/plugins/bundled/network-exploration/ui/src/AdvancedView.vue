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
  <div class="nx-view-stack">
    <section class="nx-panel">
      <div class="nx-panel-heading">
        <h2><Clock :size="17" />定时检查</h2>
        <button class="btn nx-button btn--quiet" @click="creating = !creating">
          <Plus :size="14" />添加
        </button>
      </div>
      <p class="nx-help">定期检查常用网站，结果会保存在“检测”中。</p>
      <form
        v-if="creating"
        class="nx-inline-form nx-schedule-form"
        @submit.prevent="add"
      >
        <input
          v-model="target"
          class="nx-input"
          required
          placeholder="检查哪个网站"
          aria-label="定时检查的网站"
        /><UiSelect v-model="interval" class="nx-shared-select" :options="intervalOptions" aria-label="检查间隔" data-network-interval :menu-min-width="140" />
        <button
          class="btn nx-button btn--secondary"
          :disabled="Boolean(session.busy)"
        >
          添加计划
        </button>
      </form>
      <article
        v-for="(row, index) in session.state?.automations || []"
        :key="index"
        class="nx-schedule-row"
      >
        <SundaySwitch
          size="sm"
          :label="`${row.target} 定时检查`"
          :model-value="row.enabled"
          :disabled="Boolean(session.busy)"
          @update:model-value="toggle(index)"
        />
        <div>
          <strong>{{ row.target }}</strong
          ><small>每 {{ row.interval_minutes }} 分钟检查一次</small>
        </div>
        <button
          class="btn nx-button btn--quiet"
          :disabled="Boolean(session.busy)"
          @click="preview(index)"
        >
          <Play :size="13" />试运行</button
        ><button
          class="btn nx-button btn--quiet nx-icon-button"
          :disabled="Boolean(session.busy)"
          aria-label="删除定时检查"
          @click="remove(index)"
        >
          <X :size="14" />
        </button>
      </article>
      <p
        v-if="!session.state?.automations?.length && !creating"
        class="nx-empty-inline"
      >
        还没有计划，需要时再添加。
      </p>
    </section>
    <section class="nx-panel">
      <div class="nx-panel-heading">
        <h2><Monitor :size="17" />本地设备</h2>
        <button class="btn nx-button btn--quiet" @click="loadDevices">
          查看设备
        </button>
      </div>
      <p class="nx-help">查看系统记录过的局域网邻居。</p>
      <button
        v-if="!devices"
        class="btn nx-button btn--secondary"
        :disabled="Boolean(session.busy)"
        @click="loadDevices"
      >
        读取设备列表
      </button>
      <div v-if="devices?.devices" class="nx-table-scroll">
        <table class="nx-table">
          <thead>
            <tr>
              <th>设备地址</th>
              <th>硬件地址</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in devices.devices" :key="index">
              <td>{{ row.IPAddress }}</td>
              <td>{{ row.LinkLayerAddress || "—" }}</td>
              <td>{{ row.state }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!devices.devices.length" class="nx-empty-inline">
          没有读取到设备记录。
        </p>
      </div>
    </section>
    <section class="nx-panel nx-settings-rows">
      <div>
        <span
          ><strong>网速更新频率</strong
          ><small>降低更新频率可以减少后台采样。</small></span
        ><UiSelect :model-value="sample" :options="sampleOptions" :disabled="Boolean(session.busy) || savingSample" aria-label="网速采样间隔" data-network-sampling :menu-min-width="140" @update:model-value="setSample" />
      </div>
      <div>
        <span
          ><strong>导出检查记录</strong
          ><small>保存检查结果和近期事件，方便对照。</small></span
        ><button
          class="btn nx-button btn--secondary"
          :disabled="Boolean(session.busy)"
          @click="exportReports"
        >
          <FileDown :size="14" />导出
        </button>
      </div>
    </section>
    <section v-if="session.state?.events?.length" class="nx-recent">
      <div class="nx-section-heading">
        <h2>活动记录</h2>
        <span class="nx-subtle"
          >最近 {{ Math.min(session.state.events.length, 40) }} 条</span
        >
      </div>
      <div
        v-for="(event, index) in [...session.state.events]
          .reverse()
          .slice(0, 40)"
        :key="index"
        class="nx-event"
      >
        <Check :size="14" /><span>{{ event.message }}</span
        ><time>{{ dateLabel(event.time) }}</time>
      </div>
    </section>
  </div>
</template>
