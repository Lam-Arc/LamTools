<script setup>
// user:“可交互式网络工具界面，不需要太专业”+(优先选择正在运行的应用，系统修改仍使用宿主审批及恢复接口)。
import { computed, ref } from "vue";
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
  <div class="nx-view-stack">
    <div class="nx-section-heading">
      <div>
        <h2>应用联网与恢复</h2>
        <p>只修改你选择的应用，随时检查并恢复原设置。</p>
      </div>
      <button class="nx-button nx-secondary" @click="loadApps">
        <Monitor :size="15" />选择应用
      </button>
    </div>
    <section v-if="choosing" class="nx-panel nx-form">
      <h2>管理一个应用</h2>
      <div class="nx-inline-form">
        <input
          v-if="manual"
          v-model="selected"
          class="nx-input"
          placeholder="应用 .exe 的完整路径"
          aria-label="应用路径"
        /><select
          v-else
          v-model="selected"
          class="nx-input"
          aria-label="选择应用"
        >
          <option disabled value="">从当前连接的应用中选择</option>
          <option v-for="app in apps" :key="app.path" :value="app.path">
            {{ app.process }} · {{ app.path.split("\\").at(-1) }}
          </option></select
        ><button
          class="nx-button nx-quiet"
          @click="
            manual = !manual;
            selected = '';
          "
        >
          {{ manual ? "从列表选择" : "手动输入路径" }}
        </button>
      </div>
      <div class="nx-application-actions">
        <div>
          <h3>阻止这个应用联网</h3>
          <p>创建仅作用于该应用的出站防火墙规则。</p>
          <button
            class="nx-button nx-secondary nx-danger-text"
            :disabled="!selected || Boolean(session.busy)"
            @click="apply('firewall')"
          >
            <ShieldOff :size="14" />申请阻止联网
          </button>
        </div>
        <div>
          <h3>限制这个应用的上传</h3>
          <p>降低后台上传对其他任务的影响。</p>
          <div class="nx-inline-form">
            <select
              v-model="speed"
              class="nx-input"
              aria-label="应用上传速度上限"
            >
              <option value="8000000">1 MB/s</option>
              <option value="40000000">5 MB/s</option>
              <option value="80000000">10 MB/s</option></select
            ><button
              class="nx-button nx-secondary"
              :disabled="!selected || Boolean(session.busy)"
              @click="apply('qos')"
            >
              申请限速
            </button>
          </div>
        </div>
      </div>
      <p class="nx-help">
        这两项操作可能需要 Windows 管理员权限，执行前会显示影响范围。
      </p>
    </section>
    <section class="nx-panel nx-transaction-list">
      <div class="nx-panel-heading">
        <h2><Undo2 :size="17" />网络设置记录</h2>
        <span class="nx-subtle">{{ transactions.length }} 条</span>
      </div>
      <article v-for="row in transactions" :key="row.id" class="nx-transaction">
        <span class="nx-transaction-icon"><ShieldCheck :size="18" /></span>
        <div>
          <strong>{{ title(row) }}</strong>
          <p v-if="row.request?.program">
            {{ row.request.program.split("\\").at(-1) }}
          </p>
          <small>{{ dateLabel(row.time) }}</small>
        </div>
        <span
          class="nx-status-text"
          :class="{
            'is-warning': ['external_change', 'recovery_required'].includes(
              row.status,
            ),
          }"
          >{{ status(row.status) }}</span
        ><button
          v-if="
            ['applied', 'prepared', 'recovery_required'].includes(row.status)
          "
          class="nx-button nx-secondary"
          :disabled="Boolean(session.busy)"
          @click="
            session.run('system.restore', { id: row.id }, '已检查并恢复原设置')
          "
        >
          <Undo2 :size="13" />恢复
        </button>
      </article>
      <div v-if="!transactions.length" class="nx-empty">
        <ShieldCheck :size="31" :stroke-width="1.4" /><strong
          >还没有修改网络设置</strong
        >
        <p>通过这里执行的修改，会留下可恢复的记录。</p>
      </div>
    </section>
    <p class="nx-help">
      如果设置已被其他软件或用户修改，会保留当前状态，避免直接覆盖。
    </p>
  </div>
</template>
