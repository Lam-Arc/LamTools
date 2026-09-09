import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

const configRoot = import.meta.dirname
const uiRoot = resolve(configRoot, '../ui')

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      vue: resolve(uiRoot, 'node_modules/vue'),
      'lucide-vue-next': resolve(uiRoot, 'node_modules/lucide-vue-next'),
      '@vue-flow/core': resolve(uiRoot, 'node_modules/@vue-flow/core'),
      '@vue-flow/background': resolve(uiRoot, 'node_modules/@vue-flow/background'),
      '@vue-flow/controls': resolve(uiRoot, 'node_modules/@vue-flow/controls'),
      '@vue-flow/minimap': resolve(uiRoot, 'node_modules/@vue-flow/minimap'),
      '@lamtools/ui': resolve(uiRoot, 'src'),
      '@lamtools/bundled-workflow-ui': resolve(configRoot, '../src/lamtools_core/plugins/bundled/workflow/ui/index.ts'),
      'sodium-native': 'sodium-javascript',
    },
  },
  server: {
    fs: { allow: [resolve(configRoot, '..')] },
  },
  build: {
    target: 'es2022',
    outDir: 'dist',
    emptyOutDir: true,
  },
})
