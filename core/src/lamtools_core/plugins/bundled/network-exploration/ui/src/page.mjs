// user:“可交互式网络工具界面，不需要太专业”“这样式是他妈啥？”+(独立 Vue 页面自带样式，挂载到哪个文档就注入哪个文档，不依赖宿主额外注入)。
import { createApp } from "vue";
import NetworkApp from "./NetworkApp.vue";
import QuickPanel from "./QuickPanel.vue";
import styles from "./style.css?inline";
// user:“重新设计”+(控制台排版单独一份，避免和历史样式互相覆盖)。
import redesign from "./redesign.css?inline";
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(独立插件注入共享按钮配方)。
import buttonStyles from "../../../../../../../ui/src/styles/sunday-button.css?inline";
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(独立插件只注入共享开关样式，避免影响宿主其他控件)。
import switchStyles from "../../../../../../../ui/src/styles/sunday-switch.css?inline";
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(独立插件注入共享下拉样式，包括传送到文档的菜单)。
import selectStyles from "../../../../../../../ui/src/styles/ui-select.css?inline";
function ensureStyles(root, context) {
  // user:“它自己的样式好像全部都丢了”+(样式归挂载文档与实例所有，继承宿主 CSP nonce)。
  if (context.addStyle) return context.addStyle(`${buttonStyles}\n${styles}\n${switchStyles}\n${selectStyles}`);
  const document = root.ownerDocument;
  const styleElement = document.createElement("style");
  styleElement.nonce = document.querySelector("style[nonce]")?.nonce || "";
  styleElement.dataset.networkPluginStyle = "true";
  styleElement.textContent = `${buttonStyles}\n${styles}\n${switchStyles}\n${selectStyles}`;
  document.head.append(styleElement);
  return () => styleElement.remove();
}
export function mount(root, context) {
  return mountComponent(root, context, NetworkApp);
}
export function mountQuick(root, context) {
  return mountComponent(root, context, QuickPanel);
}
function mountComponent(root, context, component) {
  const removeStyle = ensureStyles(root, context);
  let disposed = false;
  const host = document.createElement("div");
  host.className =
    component === QuickPanel ? "nx-mount nx-mount--quick" : "nx-mount";
  root.append(host);
  appId++;
  const shell = root.closest(".split-plugin-page");
  shell?.classList.add("nx-host");
  // user:“能不能让自绘样式铺满整页？”+(主区让给插件自绘页面，隐藏宿主标题条/工具栏和内边距)。
  const main = root.closest(".workspace-main");
  main?.classList.add("nx-plugin-full");
  const app = createApp(component, { context });
  app.config.idPrefix = `network-${appId}`;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    context.signal?.removeEventListener("abort", dispose);
    app.unmount();
    removeStyle();
    host.remove();
    shell?.classList.remove("nx-host");
    main?.classList.remove("nx-plugin-full");
  };
  try {
    app.mount(host);
  } catch (error) {
    dispose();
    throw error;
  }
  context.signal?.addEventListener("abort", dispose, { once: true });
  return dispose;
}
let appId = 0;
