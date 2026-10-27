// user:“可交互式网络工具界面，不需要太专业”“这样式是他妈啥？”+(独立 Vue 页面自带样式，挂载到哪个文档就注入哪个文档，不依赖宿主额外注入)。
import { createApp } from "vue";
import NetworkApp from "./NetworkApp.vue";
import QuickPanel from "./QuickPanel.vue";
import styles from "./style.css?inline";
function ensureStyles(root, context) {
  // user:“它自己的样式好像全部都丢了”+(样式归挂载文档与实例所有，继承宿主 CSP nonce)。
  if (context.addStyle) return context.addStyle(styles);
  const document = root.ownerDocument;
  const styleElement = document.createElement("style");
  styleElement.nonce = document.querySelector("style[nonce]")?.nonce || "";
  styleElement.dataset.networkPluginStyle = "true";
  styleElement.textContent = styles;
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
