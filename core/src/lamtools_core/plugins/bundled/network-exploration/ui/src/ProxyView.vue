<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络工具复用应用开关，保留原有操作与禁用条件)。
import SundaySwitch from "../../../../../../../ui/src/components/SundaySwitch.vue";
// user:“代理的功能挺简单的，就是：1 订阅分组 2 节点分组 3 节点测速 4 选择节点”+(代理页只保留这四件事)。
import { computed, ref } from "vue";
import { Link, Power, Plus } from "lucide-vue-next";
import NodePicker from "./NodePicker.vue";
import ImportProfile from "./ImportProfile.vue";
const props = defineProps({ session: Object });
const importing = ref(false);
const saved = computed(() => Boolean(props.session.state?.proxy?.config_saved));
</script>
<template>
  <div class="nx-view-stack">
    <div class="nx-section-heading">
      <div>
        <span class="nx-kicker">PROXY DESK</span>
        <h2>订阅与线路</h2>
        <p>先有订阅，再选一条线路。</p>
      </div>
      <button class="btn nx-button btn--secondary" @click="importing = !importing">
        <Plus :size="15" />{{ saved ? "更新订阅" : "添加订阅" }}
      </button>
    </div>

    <ImportProfile
      v-if="importing"
      :session="session"
      @close="importing = false"
    />

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
        </div>
        <button
          class="btn nx-button"
          :class="saved ? 'btn--quiet' : 'btn--primary'"
          @click="importing = true"
        >
          <Link :size="14" />{{ saved ? "更新订阅" : "粘贴订阅链接" }}
        </button>
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
