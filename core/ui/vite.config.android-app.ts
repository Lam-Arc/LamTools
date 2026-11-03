import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';

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
  base: './',
  build: {
    outDir: 'dist-android-app',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      // Named 'index' so the output is index.html, which Tauri loads by default.
      input: { index: resolve(__dirname, 'index-android.html') },
    },
  },
});
