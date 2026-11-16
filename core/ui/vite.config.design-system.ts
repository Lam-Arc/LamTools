import { defineConfig } from 'vite'
import base from './vite.config'
import { resolve } from 'node:path'

// user:“可视化组件展厅：参考 Storybook，直接渲染项目真实组件”+(复用 Vue 与别名配置，独立打包所有运行依赖并支持子路径部署)
export default defineConfig({
  ...base,
  base: './',
  build: {
    outDir: 'dist-design-system',
    rollupOptions: { input: resolve(__dirname, 'design-system.html') },
  },
})
