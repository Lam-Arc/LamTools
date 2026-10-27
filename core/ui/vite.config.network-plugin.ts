// user:“界面太狗屎 打回重做”+(独立 Vue 网络工具界面构建为宿主可直接加载的插件模块)。
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { resolve } from "node:path";
const folder = resolve(
  __dirname,
  "../src/lamtools_core/plugins/bundled/network-exploration/ui",
);
export default defineConfig({
  plugins: [vue()],
  // user:“ReferenceError: process is not defined”+(插件页面运行在宿主 webview 中，没有 Node 的 process；构建时直接替换 Vue 的开发分支判断)。
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  resolve: {
    alias: {
      vue: resolve(__dirname, "node_modules/vue"),
      "lucide-vue-next": resolve(__dirname, "node_modules/lucide-vue-next"),
    },
  },
  build: {
    outDir: folder,
    emptyOutDir: false,
    minify: true,
    lib: {
      entry: resolve(folder, "src/page.mjs"),
      formats: ["es"],
      fileName: () => "page.mjs",
      cssFileName: "style",
    },
    rollupOptions: {
      external: (id) => id.endsWith("/store.mjs") || id === "../store.mjs",
      output: {
        paths: (id) => (id.endsWith("store.mjs") ? "./store.mjs" : id),
      },
    },
  },
});
