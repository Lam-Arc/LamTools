import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  base: './',
  plugins: [vue()],
  resolve: {
    alias: {
      '@vue-flow/background': resolve(__dirname, 'node_modules/@vue-flow/background'),
      '@vue-flow/controls': resolve(__dirname, 'node_modules/@vue-flow/controls'),
      '@vue-flow/core': resolve(__dirname, 'node_modules/@vue-flow/core'),
      '@vue-flow/minimap': resolve(__dirname, 'node_modules/@vue-flow/minimap'),
      'lucide-vue-next': resolve(__dirname, 'node_modules/lucide-vue-next'),
      '@': resolve(__dirname, '../ui/src'),
      '@lamtools/bundled-workflow-ui': resolve(
        __dirname,
        '../src/lamtools_core/plugins/bundled/workflow/ui/index.ts',
      ),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // Mermaid is already demand-loaded only for diagram blocks; its largest
    // parser/vendor chunk is ~663 kB. Keep the warning focused on accidental
    // eager regressions instead of this intentional lazy boundary.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        desktopPluginHost: resolve(__dirname, 'desktop-plugin-host.html'),
      },
    },
  },
  server: {
    port: 5173,
    fs: {
      // The desktop shell imports Core UI source directly so Tauri can use
      // the same modules and receive their HMR updates during development.
      allow: [resolve(__dirname, '..')],
    },
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${process.env.CORE_BACKEND_PORT || '5172'}`,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
