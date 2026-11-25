<script setup>
// user:“目录这种属于是必要信息吧 为什么要藏起来”+(保存位置永远写在新建下载下面，点一次就能改，不再有「留空以保持默认」)。
import { computed, reactive, ref, watch } from "vue";
import UiSelect from "../../../../../../../ui/src/components/UiSelect.vue";
import { Download, Pause, Play, X, ChevronDown, ChevronUp, FolderOpen, ShieldCheck, ArrowUp } from "lucide-vue-next";
import { bytes, rate, taskLabel } from "./session.mjs";
const props = defineProps({ session: Object });
const tab = ref("active"),
  url = ref(""),
  filename = ref(""),
  hash = ref(""),
  route = ref("auto"),
  advanced = ref(false),
  connections = ref(8),
  speed = ref(0),
  dragging = ref(false),
  expanded = ref(""),
  editingDir = ref(false),
  savingDir = ref(false),
  dirDraft = ref("");
const connectionOptions = [1, 2, 4, 8, 16].map((value) => ({ value: String(value), label: String(value) }));
const speedOptions = [
  { value: "0", label: "不限速" },
  { value: "1048576", label: "1 MB/s" },
  { value: "5242880", label: "5 MB/s" },
  { value: "10485760", label: "10 MB/s" },
];
const routeOptions = computed(() => [
  { value: "auto", label: "自动（跟随加速）" },
  { value: "direct", label: "直接连接" },
  { value: "proxy", label: "当前代理", disabled: !props.session.state?.proxy?.running },
]);
const taskLimits = reactive({});
const pendingLimits = reactive({});
const globalConcurrency = ref("3"),
  globalRetries = ref("5"),
  globalLimit = ref("0"),
  settingsOpen = ref(false),
  savingSettings = ref(false);
const concurrencyOptions = [1, 2, 3, 4, 6, 8].map((value) => ({ value: String(value), label: `${value} 个` }));
const retryOptions = [1, 3, 5, 10, 20].map((value) => ({ value: String(value), label: `${value} 次` }));
const defaultDir = computed(() => props.session.state?.download_default || "读取中");
const customDir = computed(() => String(props.session.state?.settings?.download?.directory || ""));
const totalSpeed = computed(() => props.session.tasks.reduce((sum, task) => sum + (Number(task.downloadSpeed) || 0), 0));
const rows = computed(() =>
  props.session.tasks
    .map((task) => ({ ...props.session.state?.downloads?.find((row) => row.gid === task.gid), ...task }))
    .filter((task) => tab.value === "all" || (tab.value === "complete" ? task.status === "complete" : !["complete", "removed"].includes(task.status))),
);
const activeCount = computed(() => props.session.tasks.filter((task) => !["complete", "removed"].includes(task.status)).length);
const completeCount = computed(() => props.session.tasks.filter((task) => task.status === "complete").length);
watch(
  () => props.session.state?.settings?.download,
  (value) => {
    if (!value) return;
    globalConcurrency.value = String(value.concurrency ?? 3);
    globalRetries.value = String(value.max_tries ?? 5);
    globalLimit.value = String(value.bytes_per_second ?? 0);
  },
  { immediate: true, deep: true },
);
function progress(task) {
  return Math.min(100, (Number(task.completedLength || 0) / Math.max(1, Number(task.totalLength || 0))) * 100);
}
function remaining(task) {
  const seconds = (Number(task.totalLength || 0) - Number(task.completedLength || 0)) / Math.max(0, Number(task.downloadSpeed || 0));
  return Number.isFinite(seconds) && seconds > 0 ? (seconds < 60 ? `约 ${Math.ceil(seconds)} 秒` : `约 ${Math.ceil(seconds / 60)} 分钟`) : "等待传输";
}
async function add() {
  const name = filename.value.trim();
  const payload = {
    url: url.value.trim(),
    ...(name ? { filename: name } : {}),
    connections: Number(connections.value),
    route: route.value,
    sha256: hash.value.trim(),
    ...(Number(speed.value) > 0 ? { bytes_per_second: Number(speed.value) } : {}),
    ...(customDir.value ? { directory: defaultDir.value } : {}),
  };
  const result = await props.session.run("transfer.add", payload, "已开始下载");
  if (result) {
    url.value = "";
    filename.value = "";
    hash.value = "";
    await props.session.loadTasks();
  }
}
function dropped(event) {
  dragging.value = false;
  const text = event.dataTransfer?.getData("text/uri-list") || event.dataTransfer?.getData("text/plain") || "";
  const link = text.split(/\r?\n/).map((line) => line.trim()).find(Boolean);
  if (!link || !/^https?:\/\//i.test(link)) {
    props.session.error = "请拖入一个 HTTP 或 HTTPS 下载链接";
    return;
  }
  url.value = link;
  props.session.notice = "链接已填入，点「开始下载」";
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
  if (pendingLimits[task.gid] || value === (taskLimits[task.gid] || "0")) return;
  pendingLimits[task.gid] = true;
  try {
    const result = await props.session.run("transfer.action", { gid: task.gid, action: "limit", bytes_per_second: Number(value) }, "下载限速已更新");
    if (result && !result.cancelled) taskLimits[task.gid] = value;
  } finally {
    delete pendingLimits[task.gid];
  }
}
async function verify(task) {
  const result = await props.session.run("transfer.verify", { gid: task.gid });
  if (!result) return;
  if (result.verified === false) props.session.error = "文件与预期校验值不一致，请核对下载来源";
  else props.session.notice = result.verified === true ? "文件校验通过" : `文件校验值：${result.sha256}`;
}
function openFile(task) {
  const path = task.path || [task.directory, task.filename].filter(Boolean).join("\\");
  if (!path) {
    props.session.error = "还没有文件路径，稍后刷新一次";
    return;
  }
  props.session.openFile(path);
}
function startEditDir() {
  dirDraft.value = customDir.value || defaultDir.value;
  editingDir.value = true;
}
// user:“下载路径连个浏览都没有吗？你真就让用户手输啊？”+(点浏览弹出系统选择框，选完直接填进来)。
async function browseDir() {
  const picked = await props.session.pickDirectory();
  if (picked) dirDraft.value = picked;
}
async function saveDir(value) {
  if (savingDir.value) return;
  savingDir.value = true;
  try {
    const result = await props.session.run("settings.update", {
      revision: props.session.state?.revision,
      settings: { download: { directory: value } },
    }, value ? "保存位置已更新" : "已恢复默认保存位置");
    if (result) await props.session.refresh();
    editingDir.value = false;
  } finally {
    savingDir.value = false;
  }
}
async function saveSettings() {
  if (savingSettings.value) return;
  savingSettings.value = true;
  try {
    const result = await props.session.run("settings.update", {
      revision: props.session.state?.revision,
      settings: {
        download: {
          concurrency: Number(globalConcurrency.value),
          max_tries: Number(globalRetries.value),
          bytes_per_second: Number(globalLimit.value),
        },
      },
    }, "下载设置已保存");
    if (result) await props.session.refresh();
  } finally {
    savingSettings.value = false;
  }
}
</script>
<template>
  <div class="nx2-page">
    <form class="nx2-composer nx-download-composer" :class="{ 'is-dragging': dragging }" data-download-drop @submit.prevent="add" @dragover.prevent @dragenter.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="dropped">
      <div class="nx2-composer-line">
        <input v-model="url" name="url" class="nx2-input nx2-input--lg" required placeholder="粘贴下载链接，或把链接拖进来" aria-label="下载链接" />
        <button class="nx2-btn nx2-btn--primary" :disabled="Boolean(session.busy) || !url.trim()">开始下载</button>
      </div>

      <!-- user:“目录这种属于是必要信息吧 为什么要藏起来”+(保存位置永远写在这里，改一次就记住)。 -->
      <div class="nx2-save-line">
        <span>保存到</span>
        <b data-download-default :title="defaultDir">{{ defaultDir }}</b>
        <button v-if="!editingDir" type="button" class="nx2-link" data-change-directory @click="startEditDir">更改</button>
        <span v-if="customDir && !editingDir" class="nx2-row-hint">（自定义）</span>
      </div>
      <div v-if="editingDir" class="nx2-dir-editor">
        <input v-model="dirDraft" class="nx2-input" data-download-directory aria-label="下载默认保存位置" placeholder="例如 D:\Downloads" />
        <button type="button" class="nx2-btn" data-browse-directory @click="browseDir">浏览…</button>
        <button type="button" class="nx2-btn nx2-btn--primary" :disabled="savingDir" @click="saveDir(dirDraft.trim())">保存</button>
        <button type="button" class="nx2-btn" :disabled="savingDir" @click="editingDir = false">取消</button>
        <button v-if="customDir" type="button" class="nx2-link" :disabled="savingDir" @click="saveDir('')">恢复默认</button>
      </div>

      <button type="button" class="nx2-link nx2-advanced-toggle" :aria-expanded="advanced" @click="advanced = !advanced">
        更多选项<component :is="advanced ? ChevronUp : ChevronDown" :size="12" />
      </button>
      <div v-if="advanced" class="nx2-form-grid">
        <label><span>文件名</span><input v-model="filename" class="nx2-input" placeholder="自动使用链接中的文件名" /></label>
        <div><span>并行数量</span><UiSelect :model-value="String(connections)" :options="connectionOptions" aria-label="并行数量" data-transfer-connections :menu-min-width="100" @update:model-value="connections = Number($event)" /></div>
        <div><span>本次限速</span><UiSelect :model-value="String(speed)" :options="speedOptions" aria-label="下载限速" data-transfer-speed :menu-min-width="120" @update:model-value="speed = Number($event)" /></div>
        <label><span>SHA-256（可选）</span><input v-model="hash" class="nx2-input" placeholder="下载完成后自动校验" /></label>
        <div><span>线路</span><UiSelect v-model="route" :options="routeOptions" aria-label="下载线路" data-transfer-route :menu-min-width="180" /></div>
      </div>
    </form>

    <section class="nx2-group" data-download-settings>
      <header class="nx2-group-head">
        <h2>下载设置</h2>
        <span class="nx2-row-hint">同时 {{ globalConcurrency }} 个 · 失败重试 {{ globalRetries }} 次</span>
        <button type="button" class="nx2-link" @click="settingsOpen = !settingsOpen">{{ settingsOpen ? "收起" : "展开" }}</button>
      </header>
      <div v-if="settingsOpen" class="nx2-form-grid">
        <div><span>同时下载</span><UiSelect v-model="globalConcurrency" :options="concurrencyOptions" aria-label="同时下载数量" data-download-concurrency :menu-min-width="110" /></div>
        <div><span>失败重试</span><UiSelect v-model="globalRetries" :options="retryOptions" aria-label="失败重试次数" data-download-retries :menu-min-width="110" /></div>
        <div><span>全局限速</span><UiSelect v-model="globalLimit" :options="speedOptions" aria-label="全局下载限速" data-download-limit :menu-min-width="120" /></div>
        <div class="nx2-form-actions"><button type="button" class="nx2-btn" :disabled="savingSettings" @click="saveSettings">保存设置</button></div>
      </div>
    </section>

    <div class="nx2-toolbar">
      <div class="nx-filter-tabs">
        <button :class="{ active: tab === 'active' }" @click="tab = 'active'">进行中（{{ activeCount }}）</button>
        <button :class="{ active: tab === 'complete' }" @click="tab = 'complete'">已完成（{{ completeCount }}）</button>
        <button :class="{ active: tab === 'all' }" @click="tab = 'all'">全部</button>
      </div>
      <span class="nx2-row-hint">{{ rate(totalSpeed) }} 总速度</span>
    </div>

    <div class="nx2-tasks">
      <article v-for="task in rows" :key="task.gid" class="nx2-task" :data-task="task.gid" :title="task.status === 'complete' ? '双击打开文件' : ''" @dblclick="task.status === 'complete' && openFile(task)">
        <div class="nx2-task-main">
          <span class="nx2-task-name" :title="task.directory ? `${task.directory}\\${task.filename}` : task.filename">{{ task.filename || "未命名下载" }}</span>
          <span class="nx2-tag" :class="{ 'is-bad': task.status === 'error', 'is-ok': task.status === 'complete' }">{{ taskLabel(task.status) }}</span>
          <span v-if="task.source === 'browser'" class="nx2-tag">浏览器</span>
        </div>
        <div class="nx2-task-bar"><span class="nx2-track"><span :style="{ width: `${progress(task)}%` }" /></span><span class="nx2-task-pct">{{ Math.round(progress(task)) }}%</span></div>
        <div class="nx2-task-meta">
          <span>{{ bytes(task.completedLength) }} / {{ bytes(task.totalLength) }}</span>
          <span v-if="task.status === 'active'">{{ rate(task.downloadSpeed) }} · {{ remaining(task) }}</span>
          <span v-else-if="task.status === 'complete'" class="nx2-ellipsis" :title="task.directory">{{ task.directory || "默认目录" }}</span>
          <span v-else-if="task.status === 'error'" data-task-error class="nx2-bad">{{ task.errorText || "下载失败，请检查链接或稍后重试" }}</span>
        </div>
        <div class="nx2-task-actions">
          <button v-if="task.status === 'active' || task.status === 'waiting'" class="nx2-icon" aria-label="暂停下载" data-task-action="pause" :disabled="Boolean(session.busy)" @click="action(task, 'pause')"><Pause :size="14" /></button>
          <button v-else-if="['paused', 'recoverable'].includes(task.status)" class="nx2-icon" aria-label="继续下载" data-task-action="resume" :disabled="Boolean(session.busy)" @click="action(task, 'resume')"><Play :size="14" /></button>
          <button v-if="task.status === 'complete'" class="nx2-link" data-task-open @click="openFile(task)"><FolderOpen :size="12" />打开</button>
          <button v-if="task.status === 'complete'" class="nx2-link" @click="verify(task)"><ShieldCheck :size="12" />校验</button>
          <button v-if="!['complete', 'removed'].includes(task.status)" class="nx2-link" :disabled="Boolean(session.busy)" @click="action(task, 'first')"><ArrowUp :size="12" />优先</button>
          <button v-if="!['complete', 'removed'].includes(task.status)" class="nx2-link nx2-bad" :disabled="Boolean(session.busy)" @click="action(task, 'cancel')"><X :size="12" />取消</button>
          <button class="nx2-icon" data-task-toggle :aria-label="expanded === task.gid ? '收起下载详情' : '展开下载详情'" :aria-expanded="expanded === task.gid" @click="expanded = expanded === task.gid ? '' : task.gid"><component :is="expanded === task.gid ? ChevronUp : ChevronDown" :size="14" /></button>
        </div>
        <div v-if="expanded === task.gid" class="nx2-task-detail">
          <span class="nx2-row-hint">目录</span><b>{{ task.directory || defaultDir }}</b>
          <span class="nx2-row-hint">单任务限速</span>
          <UiSelect :model-value="taskLimits[task.gid] || '0'" :options="speedOptions" :disabled="Boolean(session.busy) || Boolean(pendingLimits[task.gid])" aria-label="下载速度限制" data-transfer-task-limit :menu-min-width="120" @update:model-value="limit(task, $event)" />
        </div>
      </article>
      <p v-if="!rows.length" class="nx2-empty-line">{{ tab === "complete" ? "还没有完成的下载。" : "没有进行中的下载，粘贴链接就能开始。" }}</p>
    </div>
  </div>
</template>
