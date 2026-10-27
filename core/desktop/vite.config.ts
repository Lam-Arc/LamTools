import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { relative, resolve, sep } from 'path'

const UI_SRC = resolve(__dirname, '../ui/src')

/**
 * user:“前端模块替换”+构建保留模块边界：每个 ui/src 源文件一个产物，
 * 应用模块之间的导入在产物里保持 `@/...` 裸说明符（由页面注入的
 * import map 落到具体文件，插件可顶掉任意一项），第三方与随包模块照常
 * 相对引用。流程：rollup 正常出块 → generateBundle 把块间相对导入改写
 * 回 `@/` 键 → 产出 importmap.base.json。
 */
function injectBaseImportMap(html: string, imports: Record<string, string>): string {
  if (html.includes('type="importmap"')) return html
  // `</script>` inside a JSON string would terminate the tag early.
  const payload = JSON.stringify({ imports }).replace(/</g, '\\u003c')
  const tag = `<script type="importmap">${payload}</script>`
  const scriptAt = html.toLowerCase().indexOf('<script')
  return scriptAt === -1 ? `${tag}\n${html}` : `${html.slice(0, scriptAt)}${tag}\n${html.slice(scriptAt)}`
}

function lamtoolsImportMap(): Plugin {
  return {
    name: 'lamtools-import-map',
    // The desktop window loads the built page from Tauri's embedded assets,
    // not from Core's HTTP SPA fallback, so the base map has to travel inside
    // the document. Without it every `@/...` import fails and the window stays
    // on the startup splash.
    // user:“a3 无法使用，界面卡住了，查一查”+(打包页必须自带基础映射)
    generateBundle: { order: 'post', handler(_options, bundle) {
      type Chunk = { type: string; fileName: string; code?: string; facadeModuleId?: string | null }
      const chunks = Object.values(bundle) as Chunk[]

      const keyOf = new Map<string, string>()
      for (const chunk of chunks) {
        if (chunk.type !== 'chunk' || !chunk.facadeModuleId) continue
        const rel = relative(UI_SRC, chunk.facadeModuleId).split(sep).join('/')
        if (rel.startsWith('..')) continue
        // Vue SFC 的虚拟子模块（?vue&type=...）没有对应源说明符：不出键，
        // 块间保持相对引用。CSS 外观同理——构建把样式落成 .css 资产，
        // 不存在可映射的 JS 块，出键只会让浏览器 404。
        if (rel.includes('?') || rel.endsWith('.css')) continue
        keyOf.set(chunk.fileName, `@/${rel}`)
      }

      // 相对导入 → 目标块文件名（按目录归一），只改写落在 ui/src 下的块。
      const importPattern = /(from\s*|import\(\s*|import\s*)("|')(\.{1,2}\/[^"']+?\.js)\2/g
      let rewritten = 0
      for (const chunk of chunks) {
        if (chunk.type !== 'chunk' || typeof chunk.code !== 'string') continue
        const directory = chunk.fileName.includes('/')
          ? chunk.fileName.slice(0, chunk.fileName.lastIndexOf('/') + 1)
          : ''
        chunk.code = chunk.code.replace(importPattern, (match, prefix: string, quote: string, spec: string) => {
          const normalized = new URL(spec, `http://x/${directory}`).pathname.replace(/^\//, '')
          const key = keyOf.get(normalized)
          if (!key) return match
          rewritten += 1
          return `${prefix}${quote}${key}${quote}`
        })
      }

      const imports: Record<string, string> = {}
      for (const [fileName, key] of keyOf.entries()) imports[key] = `/${fileName}`
      this.emitFile({
        type: 'asset',
        fileName: 'importmap.base.json',
        source: JSON.stringify({ imports }, null, 2) + '\n',
      })

      // user:“a3 无法使用，界面卡住了，查一查”+(内嵌页与 Core 返回的页都先有映射再加载模块)
      let pages = 0
      for (const asset of Object.values(bundle)) {
        if (asset.type !== 'asset' || typeof asset.source !== 'string') continue
        if (!asset.fileName.endsWith('.html')) continue
        const injected = injectBaseImportMap(asset.source, imports)
        if (injected === asset.source) continue
        asset.source = injected
        pages += 1
      }
      console.log(`[import-map] ${Object.keys(imports).length} module entries, ${rewritten} imports rewritten to bare specifiers, ${pages} page(s) injected`)
    } },
  }
}

export default defineConfig({
  base: './',
  plugins: [vue(), lamtoolsImportMap()],
  resolve: {
    alias: {
      '@vue-flow/background': resolve(__dirname, 'node_modules/@vue-flow/background'),
      '@vue-flow/controls': resolve(__dirname, 'node_modules/@vue-flow/controls'),
      '@vue-flow/core': resolve(__dirname, 'node_modules/@vue-flow/core'),
      '@vue-flow/minimap': resolve(__dirname, 'node_modules/@vue-flow/minimap'),
      'lucide-vue-next': resolve(__dirname, 'node_modules/lucide-vue-next'),
      '@': UI_SRC,
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
      },
      output: {
        preserveModules: true,
        preserveModulesRoot: resolve(__dirname, '..'),
        entryFileNames: 'assets/[name].[hash].js',
        chunkFileNames: 'assets/[name].[hash].js',
        // 第三方依赖整包进 vendor，不参与替换；随包 workflow UI 与桌面壳同理。
        manualChunks(id: string) {
          if (id.includes('/node_modules/')) return 'vendor'
          if (id.includes('plugins/bundled/workflow/ui/')) return 'bundled-workflow-ui'
          if (id.includes('/desktop/src/')) return 'desktop-shell'
          return undefined
        },
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
