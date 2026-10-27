<script setup>
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
  sample = ref(String(props.session.state?.settings?.sample_seconds || 5));
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
  if (result) creating.value = false;
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
        <button class="nx-button nx-quiet" @click="creating = !creating">
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
        /><select
          v-model="interval"
          class="nx-input nx-fit-select"
          aria-label="检查间隔"
        >
          <option value="15">每 15 分钟</option>
          <option value="30">每 30 分钟</option>
          <option value="60">每小时</option>
          <option value="360">每 6 小时</option></select
        ><button
          class="nx-button nx-secondary"
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
        <button
          class="nx-switch nx-switch--small"
          role="switch"
          :aria-label="`${row.target} 定时检查`"
          :aria-checked="row.enabled"
          :disabled="Boolean(session.busy)"
          @click="toggle(index)"
        >
          <span />
        </button>
        <div>
          <strong>{{ row.target }}</strong
          ><small>每 {{ row.interval_minutes }} 分钟检查一次</small>
        </div>
        <button
          class="nx-button nx-quiet"
          :disabled="Boolean(session.busy)"
          @click="preview(index)"
        >
          <Play :size="13" />试运行</button
        ><button
          class="nx-button nx-quiet nx-icon-button"
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
        <button class="nx-button nx-quiet" @click="loadDevices">
          查看设备
        </button>
      </div>
      <p class="nx-help">查看系统记录过的局域网邻居。</p>
      <button
        v-if="!devices"
        class="nx-button nx-secondary"
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
        ><select
          v-model="sample"
          class="nx-input nx-fit-select"
          aria-label="网速采样间隔"
          @change="
            session.run(
              'settings.update',
              {
                revision: session.state.revision,
                settings: { sample_seconds: Number(sample) },
              },
              '更新频率已保存',
            )
          "
        >
          <option value="2">每 2 秒</option>
          <option value="5">每 5 秒</option>
          <option value="10">每 10 秒</option>
          <option value="30">每 30 秒</option>
        </select>
      </div>
      <div>
        <span
          ><strong>导出检查记录</strong
          ><small>保存检查结果和近期事件，方便对照。</small></span
        ><button
          class="nx-button nx-secondary"
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
