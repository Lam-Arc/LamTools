<script setup>
// user:“提供一个普通用户可以理解的「检查网络」按钮”+(一个动作、一条结论、下面才是逐层证据)。
// user:“当把界面上的所有文字都去掉的时候，用户想干某些事，还能不能够猜到、知道应该怎么做”+(整机检查是唯一的主按钮；网站检查是第二件事，结果先给结论，证据要时才展开)。
import { computed, ref, watch } from "vue";
import { Activity, Check, X, ChevronRight, Search } from "lucide-vue-next";
import { dateLabel } from "./session.mjs";
const props = defineProps({ session: Object, report: Object });
const target = ref("github.com"),
  selected = ref(null),
  kind = ref("basic"),
  showMachineEvidence = ref(true),
  showSiteEvidence = ref(false);
watch(
  () => props.report,
  (value) => {
    if (!value) return;
    // 外部跳进来只可能是网站检查结果；整机结果留在整机区块里。
    if (value.kind === "network") network.value = value;
    else {
      selected.value = value;
      target.value = value.target || target.value;
      showSiteEvidence.value = false;
    }
  },
  { immediate: true },
);
const network = ref(
  [...(props.session.state?.reports || [])].reverse().find((row) => row.kind === "network") || null,
);
const networkBusy = computed(() => props.session.busy === "diagnose");
async function checkNetwork() {
  const result = await props.session.run("diagnose", { kind: "network" }, "");
  if (result?.report) {
    network.value = result.report;
    showMachineEvidence.value = true;
  }
}
// 网站结果不能回落到整机结果上：那会让同一份结论在页面里出现两次。
const siteReport = computed(() => {
  const rows = props.session.state?.reports || [];
  const candidate = selected.value || [...rows].reverse().find((row) => row.kind !== "network") || null;
  return candidate && candidate.kind !== "network" ? candidate : null;
});
async function diagnose() {
  const result = await props.session.diagnose(target.value, kind.value);
  if (result?.report) {
    selected.value = result.report;
    showSiteEvidence.value = false;
  }
}
function openHistory(row) {
  if (row.kind === "network") {
    network.value = row;
    showMachineEvidence.value = true;
    return;
  }
  selected.value = row;
  showSiteEvidence.value = false;
}
function stageLabel(stage) {
  return { "本机网络": "本机网络", "网关": "网关与局域网", "DNS": "域名解析", "外网连接": "外网连接", "代理": "代理设置" }[stage] || stage;
}
function siteStage(stage) {
  return { DNS: "域名解析", TCP: "建立连接", "TLS / HTTP": "安全连接与响应", Ping: "响应延迟", Traceroute: "访问路径", ICMP: "网络响应" }[stage] || stage;
}
const history = computed(() => [...(props.session.state?.reports || [])].reverse().slice(0, 8));
</script>
<template>
  <div class="nx2-page">
    <!-- 整机检查：图标 + 一句话 + 一个主按钮，和首页的操作台同一种形状。 -->
    <section class="nx2-check" data-network-check-block>
      <div>
        <h2><Activity :size="16" :stroke-width="1.9" />检查这台电脑的网络</h2>
        <p class="nx2-note">本机、网关、域名解析、外网、代理五层一次看完，不用先想一个网址。</p>
      </div>
      <button class="nx2-btn nx2-btn--primary nx2-btn--lg" data-network-check :disabled="networkBusy" @click="checkNetwork">
        <Activity :size="15" />{{ networkBusy ? "检查中…" : "检查网络" }}
      </button>
    </section>

    <section v-if="network" class="nx2-group" data-network-result>
      <p class="nx2-verdict" :class="{ 'nx2-bad': network.failures > 0 }">{{ network.conclusion?.text || "检查完成" }}</p>
      <p class="nx2-note">{{ network.conclusion?.suggestion }}</p>
      <button class="nx2-link" :aria-expanded="showMachineEvidence" data-network-evidence-toggle @click="showMachineEvidence = !showMachineEvidence">
        {{ showMachineEvidence ? "收起检查详情" : "查看检查详情" }}<ChevronRight :size="12" :class="{ 'is-open': showMachineEvidence }" />
      </button>
      <div v-if="showMachineEvidence" class="nx2-rows">
        <div v-for="(check, index) in network.checks || []" :key="index" class="nx2-row nx2-row--cols">
          <span class="nx2-row-label">{{ stageLabel(check.stage) }}</span>
          <span class="nx2-tag" :class="check.ok ? 'is-ok' : 'is-bad'"><component :is="check.ok ? Check : X" :size="11" />{{ check.ok ? "通过" : "未通过" }}</span>
          <span class="nx2-row-hint nx2-ellipsis" :title="check.evidence">{{ check.evidence }}</span>
        </div>
      </div>
      <p class="nx2-note">检查时间 {{ dateLabel(network.time) }} · 只报告测量结果，没有改动任何系统设置。</p>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head"><h2>检查某个网站</h2></header>
      <form class="nx2-composer nx2-composer--inline" data-diagnose-form @submit.prevent="diagnose">
        <input v-model="target" name="target" class="nx2-input nx2-input--lg" placeholder="例如 github.com" required aria-label="检测网站" />
        <button class="nx2-btn" :disabled="Boolean(session.busy)"><Search :size="13" />{{ session.busy === "diagnose" ? "检查中…" : "开始检测" }}</button>
      </form>
      <div class="nx2-radio-row">
        <label><input v-model="kind" type="radio" value="basic" />快速检查</label>
        <label><input v-model="kind" type="radio" value="ping" />加测延迟</label>
        <label><input v-model="kind" type="radio" value="traceroute" />查看访问路径</label>
      </div>

      <div v-if="siteReport" class="nx2-site-result" data-site-result>
        <p class="nx2-verdict" :class="{ 'nx2-bad': siteReport.failures > 0 }">
          <b class="nx2-mono">{{ siteReport.target }}</b>
          <span class="nx2-row-hint">{{ siteReport.failures > 0 ? "有未通过的检查" : "检查通过" }}</span>
        </p>
        <p class="nx2-note">{{ siteReport.conclusion?.text }}<template v-if="siteReport.conclusion?.suggestion"> · {{ siteReport.conclusion.suggestion }}</template></p>
        <button class="nx2-link" :aria-expanded="showSiteEvidence" data-site-evidence-toggle @click="showSiteEvidence = !showSiteEvidence">
          {{ showSiteEvidence ? "收起" : "查看检查详情" }}<ChevronRight :size="12" :class="{ 'is-open': showSiteEvidence }" />
        </button>
        <div v-if="showSiteEvidence" class="nx2-rows" data-check-evidence>
          <div v-for="(check, index) in siteReport.checks || []" :key="index" class="nx2-row nx2-row--cols">
            <span class="nx2-row-label">{{ siteStage(check.stage) }}</span>
            <span class="nx2-tag" :class="check.ok ? 'is-ok' : 'is-bad'"><component :is="check.ok ? Check : X" :size="11" />{{ check.ok ? "通过" : "未通过" }}</span>
            <span class="nx2-row-hint">{{ check.ms != null ? `${check.ms} ms` : "" }}</span>
            <span class="nx2-row-hint nx2-ellipsis" :title="check.evidence">{{ check.evidence || check.address || check.addresses?.join("、") || (check.status ? `响应 ${check.status}` : "") }}</span>
          </div>
        </div>
      </div>
      <p v-else class="nx2-empty-line">还没有检查过网站。输入域名后点「开始检测」。</p>
    </section>

    <section v-if="history.length" class="nx2-group">
      <header class="nx2-group-head"><h2>最近检查</h2><span class="nx2-row-hint">{{ history.length }} 条</span></header>
      <div class="nx2-rows">
        <button v-for="row in history" :key="row.id" class="nx2-row nx2-row--button" @click="openHistory(row)">
          <span class="nx2-row-value">{{ row.kind === "network" ? "整机网络" : row.target }}</span>
          <span class="nx2-tag" :class="row.failures > 0 ? 'is-bad' : 'is-ok'">{{ row.failures > 0 ? "有未通过项" : "通过" }}</span>
          <span class="nx2-row-hint">{{ dateLabel(row.time) }}</span>
          <ChevronRight :size="13" />
        </button>
      </div>
    </section>
  </div>
</template>
