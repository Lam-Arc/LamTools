import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 官网展示区直接复用 core/ui 的真实组件与样式（保证像素级一致）。
// 关键：vue 必须 alias 到本项目的单例，否则 core/ui 组件会加载第二份 vue 实例导致白屏。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // core/ui 真实组件库
      '@ui': fileURLToPath(new URL('../core/ui/src', import.meta.url)),
      // 完整 LamToolsApp 会按需加载内置 Workflow UI；这些 alias 与桌面端保持一致。
      '@lamtools/bundled-workflow-ui': fileURLToPath(new URL('../core/src/lamtools_core/plugins/bundled/workflow/ui/index.ts', import.meta.url)),
      '@vue-flow/background': fileURLToPath(new URL('../core/ui/node_modules/@vue-flow/background', import.meta.url)),
      '@vue-flow/controls': fileURLToPath(new URL('../core/ui/node_modules/@vue-flow/controls', import.meta.url)),
      '@vue-flow/core': fileURLToPath(new URL('../core/ui/node_modules/@vue-flow/core', import.meta.url)),
      '@vue-flow/minimap': fileURLToPath(new URL('../core/ui/node_modules/@vue-flow/minimap', import.meta.url)),
      'lucide-vue-next': fileURLToPath(new URL('./node_modules/lucide-vue-next', import.meta.url)),
      // 强制所有 vue import（含 core/ui 组件内部）解析到本项目的 vue 单例
      vue: fileURLToPath(new URL('./node_modules/vue', import.meta.url)),
    },
  },
  server: {
    // 允许 dev 服务器访问 core/ui（在项目根之外）
    fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] },
    port: 5199,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./index.html', import.meta.url)),
        preview: fileURLToPath(new URL('./preview.html', import.meta.url)),
      },
    },
    // 官网直接挂载完整产品，主入口包含真实工作台；Mermaid 等重模块仍保持按需分包。
    chunkSizeWarningLimit: 1200,
  },
})
