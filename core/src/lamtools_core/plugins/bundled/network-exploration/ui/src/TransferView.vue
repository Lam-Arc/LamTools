<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“可交互式网络工具界面，不需要太专业”+(下载从任务行暂停和继续，不要求用户填写任务 ID)。
import { computed, reactive, ref } from "vue";
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(下载设置复用共享下拉，保留数值、线路禁用与单任务限速)。
import UiSelect from "../../../../../../../ui/src/components/UiSelect.vue";
import {
  Download,
  FileDown,
  Pause,
  Play,
  X,
  ChevronDown,
  ChevronUp,
  ShieldCheck,
  RefreshCw,
  ArrowUp,
} from "lucide-vue-next";
import { bytes, rate, taskLabel } from "./session.mjs";
const props = defineProps({ session: Object });
const tab = ref("active"),
  url = ref(""),
  filename = ref(""),
  directory = ref(""),
  hash = ref(""),
  route = ref("auto"),
  advanced = ref(false),
  connections = ref(8),
  speed = ref(0),
  dragging = ref(false),
  expanded = ref("");
const connectionOptions = [1, 2, 4, 8, 16].map(value => ({ value: String(value), label: String(value) }));
const speedOptions = [{ value: '0', label: '不限速' }, { value: '1048576', label: '1 MB/s' }, { value: '5242880', label: '5 MB/s' }, { value: '10485760', label: '10 MB/s' }];
const routeOptions = computed(() => [{ value: 'auto', label: '自动（跟随加速）' }, { value: 'direct', label: '直接连接' }, { value: 'proxy', label: '当前代理', disabled: !props.session.state?.proxy?.running }]);
const taskLimits = reactive({});
const pendingLimits = reactive({});
const totalSpeed = computed(() =>
  props.session.tasks.reduce(
    (sum, task) => sum + (Number(task.downloadSpeed) || 0),
    0,
  ),
);
const rows = computed(() =>
  props.session.tasks
    .map((task) => ({
      ...props.session.state?.downloads?.find((row) => row.gid === task.gid),
      ...task,
    }))
    .filter(
      (task) =>
        tab.value === "all" ||
        (tab.value === "complete"
          ? task.status === "complete"
          : !["complete", "removed"].includes(task.status)),
    ),
);
const activeCount = computed(
  () =>
    props.session.tasks.filter(
      (task) => !["complete", "removed"].includes(task.status),
    ).length,
);
const completeCount = computed(
  () => props.session.tasks.filter((task) => task.status === "complete").length,
);
function progress(task) {
  return Math.min(
    100,
    (Number(task.completedLength || 0) /
      Math.max(1, Number(task.totalLength || 0))) *
      100,
  );
}
function remaining(task) {
  const seconds =
    (Number(task.totalLength || 0) - Number(task.completedLength || 0)) /
    Math.max(0, Number(task.downloadSpeed || 0));
  return Number.isFinite(seconds) && seconds > 0
    ? seconds < 60
      ? `约 ${Math.ceil(seconds)} 秒`
      : `约 ${Math.ceil(seconds / 60)} 分钟`
    : "等待传输";
}
async function add() {
  // user:“修”+(完整下载页与快捷入口共用后台默认值和参数验证)。
  const name = filename.value.trim();
  const payload = {
    url: url.value.trim(),
    ...(name ? { filename: name } : {}),
    connections: Number(connections.value),
    route: route.value,
    sha256: hash.value.trim(),
    ...(Number(speed.value) > 0
      ? { bytes_per_second: Number(speed.value) }
      : {}),
    ...(directory.value.trim() ? { directory: directory.value.trim() } : {}),
  };
  const result = await props.session.run("transfer.add", payload, "已开始下载");
  if (result) {
    url.value = "";
    filename.value = "";
    hash.value = "";
    await props.session.loadTasks();
  }
}
// user:“通过一个链接或者拖拽放进来之后，点‘开始下载’”+(拖入链接即可填入，不要求用户先找按钮)。
function dropped(event) {
  dragging.value = false;
  const text =
    event.dataTransfer?.getData("text/uri-list") ||
    event.dataTransfer?.getData("text/plain") ||
    "";
  const link = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);
  if (!link || !/^https?:\/\//i.test(link)) {
    props.session.error = "请拖入一个 HTTP 或 HTTPS 下载链接";
    return;
  }
  url.value = link;
  props.session.notice = "链接已填入，点“开始下载”";
}
async function action(task, action) {
  if (task.status === "recoverable" && action === "resume") {
    const recovered = await props.session.run("transfer.recover", {});
    if (!recovered) return;
  }
  await props.session.run("transfer.action", { gid: task.gid, action });
  await props.session.loadTasks();
}
async function limit(task, value) {
  // user:“确保视觉、功能和交互不退化”+(限速成功后才更新显示；失败或取消可重试，处理中防止重复提交)。
  if (pendingLimits[task.gid] || value === (taskLimits[task.gid] || "0")) return;
  pendingLimits[task.gid] = true;
  try {
    const result = await props.session.run(
      "transfer.action",
      { gid: task.gid, action: "limit", bytes_per_second: Number(value) },
      "下载限速已更新",
    );
    if (result && !result.cancelled) taskLimits[task.gid] = value;
  } finally {
    delete pendingLimits[task.gid];
  }
}
async function verify(task) {
  const result = await props.session.run("transfer.verify", { gid: task.gid });
  if (!result) return;
  if (result.verified === false)
    props.session.error = "文件与预期校验值不一致，请核对下载来源";
  else
    props.session.notice =
      result.verified === true
        ? "文件校验通过"
        : `文件校验值：${result.sha256}`;
}
</script>
<template>
  <div class="nx-view-stack">
    <div class="nx-section-heading">
      <div>
        <h2>下载</h2>
        <p>粘贴链接或把链接拖进来，点“开始下载”。</p>
      </div>
    </div>
    <div class="nx-download-stats">
      <div>
        <span>进行中</span><strong>{{ activeCount }}</strong>
      </div>
      <div>
        <span>已完成</span><strong>{{ completeCount }}</strong>
      </div>
      <div>
        <span>总速度</span><strong>{{ rate(totalSpeed) }}</strong>
      </div>
    </div>
    <form
      class="nx-panel nx-download-composer"
      :class="{ 'is-dragging': dragging }"
      data-download-drop
      @submit.prevent="add"
      @dragover.prevent
      @dragenter.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="dropped"
    >
      <div class="nx-panel-heading">
        <h2><Download :size="17" />新建下载</h2>
        <span class="nx-subtle">支持 HTTP / HTTPS</span>
      </div>
      <div class="nx-inline-form">
        <input
          v-model="url"
          name="url"
          class="nx-input"
          required
          placeholder="粘贴下载链接，或把链接拖到这里"
          aria-label="下载链接"
        /><button
          class="btn nx-button btn--primary"
          :disabled="Boolean(session.busy) || !url.trim()"
        >
          开始下载
        </button>
      </div>
      <div class="nx-download-options">
        <div class="nx-download-option"><span>并行数量</span><UiSelect :model-value="String(connections)" :options="connectionOptions" aria-label="并行数量" data-transfer-connections :menu-min-width="100" @update:model-value="connections = Number($event)" /></div>
        <div class="nx-download-option"><span>下载限速</span><UiSelect :model-value="String(speed)" :options="speedOptions" aria-label="下载限速" data-transfer-speed :menu-min-width="120" @update:model-value="speed = Number($event)" /></div>
      </div>
      <button
        type="button"
        class="btn nx-button btn--quiet nx-options-button"
        :aria-expanded="advanced"
        @click="advanced = !advanced"
      >
        更多选项<ChevronDown :size="13" />
      </button>
      <div v-if="advanced" class="nx-form-grid">
        <label
          ><span>文件名</span
          ><input
            v-model="filename"
            class="nx-input"
            placeholder="自动使用链接中的文件名" /></label
        ><label
          ><span>保存目录</span
          ><input
            v-model="directory"
            class="nx-input"
            placeholder="留空使用默认下载目录" /></label
        ><label
          ><span>文件校验值（可选）</span
          ><input
            v-model="hash"
            class="nx-input"
            placeholder="SHA-256" /></label
        ><div class="nx-form-field"><span>下载线路</span><UiSelect v-model="route" :options="routeOptions" aria-label="下载线路" data-transfer-route :menu-min-width="180" /></div>
      </div>
    </form>
    <div class="nx-list-toolbar">
      <div class="nx-filter-tabs">
        <button :class="{ active: tab === 'active' }" @click="tab = 'active'">
          进行中<span>{{ activeCount }}</span></button
        ><button
          :class="{ active: tab === 'complete' }"
          @click="tab = 'complete'"
        >
          已完成<span>{{ completeCount }}</span></button
        ><button :class="{ active: tab === 'all' }" @click="tab = 'all'">
          全部
        </button>
      </div>
      <button
        class="btn nx-button btn--quiet nx-icon-button"
        aria-label="刷新下载列表"
        @click="session.loadTasks()"
      >
        <RefreshCw :size="15" />
      </button>
    </div>
    <section class="nx-panel nx-task-list">
      <article
        v-for="task in rows"
        :key="task.gid"
        class="nx-download-row"
        :data-task="task.gid"
      >
        <div class="nx-file-icon">
          <FileDown :size="22" :stroke-width="1.5" />
        </div>
        <div class="nx-download-body">
          <div class="nx-task-title">
            <strong>{{ task.filename || "未命名下载" }}</strong
            ><span :class="{ 'nx-state-error': task.status === 'error' }">{{
              taskLabel(task.status)
            }}</span>
          </div>
          <div
            class="nx-progress-track"
            role="progressbar"
            :aria-valuenow="Math.round(progress(task))"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-label="`${task.filename || '下载'}的进度`"
          >
            <span :style="{ width: `${progress(task)}%` }" />
          </div>
          <div class="nx-task-meta">
            <span
              >{{ bytes(task.completedLength)
              }}<span class="nx-meta-divider"> / </span
              >{{ bytes(task.totalLength) }}</span
            ><span v-if="task.status === 'active'"
              >{{ rate(task.downloadSpeed)
              }}<span class="nx-meta-divider">·</span
              >{{ remaining(task) }}</span
            ><span v-else-if="task.status === 'complete'">已保存到本地</span
            ><span v-else-if="task.status === 'error'"
              >链接可能失效，或下载源暂时不可用</span
            >
          </div>
        </div>
        <div class="nx-task-controls">
          <button
            v-if="task.status === 'active' || task.status === 'waiting'"
            class="btn nx-button btn--secondary nx-icon-button"
            aria-label="暂停下载"
            data-task-action="pause"
            :disabled="Boolean(session.busy)"
            @click="action(task, 'pause')"
          >
            <Pause :size="15" /></button
          ><button
            v-else-if="['paused', 'recoverable'].includes(task.status)"
            class="btn nx-button btn--secondary nx-icon-button"
            aria-label="继续下载"
            data-task-action="resume"
            :disabled="Boolean(session.busy)"
            @click="action(task, 'resume')"
          >
            <Play :size="15" /></button
          ><button
            class="btn nx-button btn--quiet nx-icon-button"
            :aria-label="
              expanded === task.gid ? '收起下载详情' : '展开下载详情'
            "
            :aria-expanded="expanded === task.gid"
            @click="expanded = expanded === task.gid ? '' : task.gid"
          >
            <component
              :is="expanded === task.gid ? ChevronUp : ChevronDown"
              :size="15"
            />
          </button>
        </div>
        <div v-if="expanded === task.gid" class="nx-task-details">
          <span class="nx-subtle">{{ task.directory || "默认下载目录" }}</span>
          <div class="nx-actions">
            <div class="nx-small-select"><span>下载速度</span><UiSelect :model-value="taskLimits[task.gid] || '0'" :options="speedOptions" :disabled="Boolean(session.busy) || Boolean(pendingLimits[task.gid])" aria-label="下载速度限制" data-transfer-task-limit :menu-min-width="120" @update:model-value="limit(task, $event)" /></div>
            <button
              v-if="!['complete', 'removed'].includes(task.status)"
              class="btn nx-button btn--quiet"
              :disabled="Boolean(session.busy)"
              @click="action(task, 'first')"
            >
              <ArrowUp :size="13" />优先下载</button
            ><button
              v-if="task.status === 'complete'"
              class="btn nx-button btn--quiet"
              :disabled="Boolean(session.busy)"
              @click="verify(task)"
            >
              <ShieldCheck :size="13" />校验文件</button
            ><button
              v-if="!['complete', 'removed'].includes(task.status)"
              class="btn nx-button btn--quiet nx-danger-text"
              :disabled="Boolean(session.busy)"
              @click="action(task, 'cancel')"
            >
              <X :size="13" />取消下载
            </button>
          </div>
        </div>
      </article>
      <div v-if="!rows.length" class="nx-empty">
        <Download :size="32" :stroke-width="1.3" /><strong>{{
          tab === "complete" ? "还没有完成的下载" : "准备好下载了吗？"
        }}</strong>
        <p>
          {{
            tab === "complete"
              ? "完成的文件会显示在这里。"
              : "把链接放到上面的框里，就会开始下载。"
          }}
        </p>
      </div>
    </section>
  </div>
</template>
