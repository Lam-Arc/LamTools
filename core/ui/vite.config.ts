import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';

const coreBackendPort = process.env.CORE_BACKEND_PORT || '5172';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@vue-flow/background': resolve(__dirname, 'node_modules/@vue-flow/background'),
      '@vue-flow/controls': resolve(__dirname, 'node_modules/@vue-flow/controls'),
      '@vue-flow/core': resolve(__dirname, 'node_modules/@vue-flow/core'),
      '@vue-flow/minimap': resolve(__dirname, 'node_modules/@vue-flow/minimap'),
      'lucide-vue-next': resolve(__dirname, 'node_modules/lucide-vue-next'),
      '@': resolve(__dirname, 'src'),
      '@lamtools/bundled-workflow-ui': resolve(
        __dirname,
        '../src/lamtools_core/plugins/bundled/workflow/ui/index.ts',
      ),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${coreBackendPort}`,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'LamtoolsUI',
      formats: ['es'],
      fileName: 'lamtools-ui',
    },
    rollupOptions: {
      external: ['vue'],
      output: {
        globals: {
          vue: 'Vue',
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
  },
});
