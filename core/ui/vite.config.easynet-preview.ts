// user:“整个 easynet 与其相关界面，浏览器打开我随时看”+(独立预览构建：真实组件 + 示例数据，不依赖宿主)。
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [vue()],
  root: __dirname,
  resolve: {
    alias: {
      vue: resolve(__dirname, "node_modules/vue"),
      "lucide-vue-next": resolve(__dirname, "node_modules/lucide-vue-next"),
      "@": resolve(__dirname, "src"),
    },
  },
  server: { host: "127.0.0.1", port: 5179, strictPort: true },
  build: {
    outDir: resolve(__dirname, "../../.build/easynet-preview"),
    emptyOutDir: true,
    rollupOptions: { input: resolve(__dirname, "easynet-preview.html") },
  },
});
