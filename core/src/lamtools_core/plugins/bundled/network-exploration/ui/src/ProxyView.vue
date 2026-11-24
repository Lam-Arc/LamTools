<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络工具复用应用开关，保留原有操作与禁用条件)。
import SundaySwitch from "../../../../../../../ui/src/components/SundaySwitch.vue";
// user:“代理的功能挺简单的，就是：1 订阅分组 2 节点分组 3 节点测速 4 选择节点”+(代理页只保留这四件事)。
import { computed, ref } from "vue";
import { Link, Power } from "lucide-vue-next";
import NodePicker from "./NodePicker.vue";
import { dateLabel } from "./session.mjs";
import ImportProfile from "./ImportProfile.vue";
const props = defineProps({ session: Object });
const importing = ref(false);
const switching = ref(false);
const saved = computed(() => Boolean(props.session.state?.proxy?.config_saved));
// user:“怎么切换订阅”+(记住导入过的订阅来源，随时切回去；列表只显示主机，不显示带令牌的原始链接)。
const subscriptions = computed(() => props.session.state?.subscriptions || []);
const activeSubscription = computed(
  () => subscriptions.value.find((row) => row.active) || null,
);
async function activateSubscription(row) {
  const result = await props.session.run(
    "proxy.subscriptions",
    { action: "activate", id: row.id },
    `已切换到 ${row.host}`,
  );
  if (result) {
    switching.value = false;
    await props.session.loadProxy();
  }
}
async function removeSubscription(row) {
  await props.session.run(
    "proxy.subscriptions",
    { action: "remove", id: row.id },
    "已删除这条订阅记录",
  );
}
</script>
<template>
  <div class="nx-view-stack">
    <div class="nx-section-heading">
      <div>
        <span class="nx-kicker">PROXY DESK</span>
        <h2>订阅与线路</h2>
        <p>先有订阅，再选一条线路。</p>
      </div>
    </div>

    <ImportProfile
      v-if="importing"
      :session="session"
      @close="importing = false"
    />

    <!-- user:“怎么切换订阅”+(列表里只有主机与时间；切换会重新拉取该订阅并重连)。 -->
    <section
      v-if="switching && subscriptions.length"
      class="nx-panel nx-subscribe-list"
      data-subscription-list
    >
      <div class="nx-panel-heading">
        <h2>已保存的订阅</h2>
        <span class="nx-subtle">切换会重新拉取一次订阅</span>
      </div>
      <div
        v-for="row in subscriptions"
        :key="row.id"
        class="nx-subscribe-row"
        :data-subscription="row.id"
      >
        <span class="nx-subscribe-host" :title="row.host">{{ row.host }}</span>
        <span class="nx-subtle">{{ dateLabel(row.saved_at) }}</span>
        <span v-if="row.active" class="nx-quick-state is-live">当前</span>
        <button
          v-else
          class="btn nx-button btn--quiet"
          :disabled="Boolean(session.busy)"
          @click="activateSubscription(row)"
        >
          切换
        </button>
        <button
          class="btn nx-button btn--quiet nx-danger-text"
          :disabled="Boolean(session.busy)"
          @click="removeSubscription(row)"
        >
          删除
        </button>
      </div>
    </section>

    <div class="nx-proxy-top">
      <section class="nx-panel nx-subscribe-summary">
        <span class="nx-kicker">01 / 订阅</span>
        <div class="nx-subscribe-copy">
          <h3>{{ saved ? "订阅已保存" : "还没有订阅" }}</h3>
          <p>
            {{
              saved
                ? "已使用当前 Windows 账户加密保存。更新订阅会自动重连。"
                : "粘贴服务商给你的 HTTPS 订阅链接，节点会自动出现。"
            }}
          </p>
          <p v-if="activeSubscription" class="nx-subtle" data-active-subscription>
            当前订阅：{{ activeSubscription.host }}
          </p>
          <p v-else-if="saved" class="nx-subtle">当前使用的是导入的配置文件</p>
        </div>
        <div class="nx-subscribe-actions">
          <button
            class="btn nx-button"
            :class="saved ? 'btn--quiet' : 'btn--primary'"
            @click="importing = true"
          >
            <Link :size="14" />{{ saved ? "更新订阅" : "粘贴订阅链接" }}
          </button>
          <button
            v-if="subscriptions.length"
            class="btn nx-button btn--quiet"
            data-toggle-subscriptions
            :aria-expanded="switching"
            @click="switching = !switching"
          >
            {{ switching ? "收起订阅列表" : `切换订阅（${subscriptions.length}）` }}
          </button>
        </div>
      </section>

      <section class="nx-panel nx-proxy-connection">
        <span class="nx-kicker">02 / 连接</span>
        <div class="nx-proxy-connection-row">
          <span class="nx-route-icon"><Power :size="18" /></span>
          <div class="nx-control-copy">
            <strong>{{ session.state?.proxy?.running ? "已连接" : "未连接" }}</strong>
            <p>
              {{
                !saved
                  ? "先保存订阅，才能启动代理。"
                  : session.state?.proxy?.running
                    ? "节点已加载，可以在下面切换。"
                    : "开启后加载订阅里的节点。"
              }}
            </p>
          </div>
          <SundaySwitch
            data-proxy-switch
            label="代理连接"
            :model-value="Boolean(session.state?.proxy?.running)"
            :disabled="Boolean(session.busy) || !saved"
            @update:model-value="session.toggleProxy()"
          />
        </div>
      </section>
    </div>

    <NodePicker :session="session" @import="importing = true" />
  </div>
</template>
