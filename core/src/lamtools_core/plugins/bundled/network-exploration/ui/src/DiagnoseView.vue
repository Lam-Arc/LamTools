<script setup>
// user:“可交互式网络工具界面，不需要太专业”+(诊断按可理解的阶段显示真实证据，原始参数不占据主界面)。
import { computed, ref, watch } from "vue";
import {
  Activity,
  Check,
  X,
  Globe,
  Search,
  Clock,
  ChevronDown,
  ChevronRight,
  ArrowUpRight,
} from "lucide-vue-next";
import { dateLabel } from "./session.mjs";
const props = defineProps({ session: Object, report: Object });
const target = ref("github.com"),
  selected = ref(null),
  details = ref(false),
  kind = ref("basic");
watch(
  () => props.report,
  (value) => {
    if (value) {
      selected.value = value;
      target.value = value.target;
    }
  },
  { immediate: true },
);
const current = computed(
  () => selected.value || props.session.state?.reports?.at(-1),
);
function label(stage) {
  return (
    {
      DNS: "找到网站地址",
      TCP: "建立网络连接",
      "TLS / HTTP": "检查安全连接与响应",
      Ping: "检查响应延迟",
      Traceroute: "检查访问路径",
      ICMP: "检查网络响应",
    }[stage] || stage
  );
}
async function diagnose() {
  const result = await props.session.diagnose(target.value, kind.value);
  if (result?.report) {
    selected.value = result.report;
    details.value = false;
  }
}
</script>
<template>
  <div class="nx-view-stack">
    <section class="nx-panel nx-diagnose-start">
      <div class="nx-diagnose-symbol">
        <Activity :size="25" :stroke-width="1.5" />
      </div>
      <h2>看看哪里没连上</h2>
      <p>输入一个网站，检查地址解析、连接和响应。</p>
      <form
        class="nx-inline-form"
        data-diagnose-form
        @submit.prevent="diagnose"
      >
        <label class="nx-input-with-icon"
          ><Globe :size="16" /><input
            v-model="target"
            name="target"
            class="nx-input"
            placeholder="例如 github.com"
            required
            aria-label="检测网站" /></label
        ><button class="nx-button nx-primary" :disabled="Boolean(session.busy)">
          <Search :size="15" />{{
            session.busy === "diagnose" ? "检查中…" : "开始检测"
          }}
        </button>
      </form>
      <div class="nx-diagnose-options">
        <label
          ><input v-model="kind" type="radio" value="basic" />快速检查</label
        ><label
          ><input v-model="kind" type="radio" value="ping" />加测延迟</label
        ><label
          ><input
            v-model="kind"
            type="radio"
            value="traceroute"
          />查看访问路径</label
        >
      </div>
    </section>
    <section
      v-if="session.busy === 'diagnose'"
      class="nx-panel nx-diagnose-pending"
      aria-live="polite"
    >
      <div class="nx-skeleton nx-skeleton-title" />
      <p>正在检查网站地址、连接和安全响应…</p>
      <div v-for="n in 3" :key="n" class="nx-skeleton nx-skeleton-row" />
    </section>
    <section v-else-if="current" class="nx-panel nx-report">
      <div class="nx-report-heading">
        <span
          class="nx-result-icon"
          :class="{ 'is-failure': current.failures > 0 }"
          ><Check v-if="!current.failures" :size="22" /><X v-else :size="22"
        /></span>
        <div>
          <h2>{{ current.failures > 0 ? "发现未通过的检查" : "检查通过" }}</h2>
          <p>
            {{ current.target }}<span class="nx-meta-divider">·</span
            >{{ dateLabel(current.time) }}
          </p>
        </div>
      </div>
      <div class="nx-check-list">
        <div
          v-for="(check, index) in current.checks || []"
          :key="index"
          class="nx-check-row"
        >
          <span class="nx-check-status" :class="{ 'is-failure': !check.ok }"
            ><Check v-if="check.ok" :size="14" /><X v-else :size="14" /></span
          ><strong>{{ label(check.stage) }}</strong
          ><span>{{ check.ok ? "通过" : "未通过" }}</span
          ><time v-if="check.ms != null">{{ check.ms }} ms</time>
        </div>
      </div>
      <p v-if="current.recommendation" class="nx-report-advice">
        {{ current.recommendation }}
      </p>
      <button
        class="nx-button nx-quiet nx-report-detail-button"
        :aria-expanded="details"
        @click="details = !details"
      >
        {{ details ? "收起" : "查看" }}检查详情<ChevronDown :size="13" />
      </button>
      <div v-if="details" class="nx-check-evidence">
        <div v-for="(check, index) in current.checks || []" :key="index">
          <strong>{{ label(check.stage) }}</strong>
          <p>
            {{
              check.evidence ||
              check.address ||
              check.addresses?.join("、") ||
              (check.status ? `网站响应：${check.status}` : "未提供额外信息")
            }}
          </p>
        </div>
      </div>
    </section>
    <section v-if="session.state?.reports?.length" class="nx-history">
      <div class="nx-section-heading">
        <h2>最近检查</h2>
        <span class="nx-subtle">{{ session.state.reports.length }} 条记录</span>
      </div>
      <button
        v-for="report in [...session.state.reports].reverse().slice(0, 12)"
        :key="report.id"
        class="nx-history-row"
        @click="selected = report"
      >
        <span
          class="nx-history-result"
          :class="{ 'is-failure': report.failures > 0 }"
          ><component :is="report.failures ? X : Check" :size="14" /></span
        ><strong>{{ report.target }}</strong
        ><span>{{ report.failures ? "有未通过的检查" : "检查通过" }}</span
        ><time>{{ dateLabel(report.time) }}</time
        ><ChevronRight :size="15" />
      </button>
    </section>
    <div v-else-if="!current" class="nx-empty nx-diagnose-empty">
      <Clock :size="25" /><span>检查记录会保存在这里，方便下次对照。</span>
    </div>
  </div>
</template>
