import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'

/* Render stage for the demo film.
 *
 * The stage mounts the real `core/ui` application and drives it entirely from
 * the outside. Dependency resolution is the one unusual part: this folder has
 * a junction to `core/ui/node_modules` (created by capture.mjs), so every bare
 * import — vue, pinia, the vue-flow packages, lucide — resolves to the single
 * copy the product itself uses. That is deliberate: a second copy of Vue in
 * the graph is exactly the failure the website's preview config warns about.
 */

const repo = (path: string) => fileURLToPath(new URL(`../../../${path}`, import.meta.url))

export default {
  plugins: [vue()],
  resolve: {
    alias: {
      '@ui': repo('core/ui/src'),
      // The full application loads its bundled Workflow UI lazily; the desktop
      // and the website both alias this, so the stage stays on the same code.
      '@lamtools/bundled-workflow-ui': repo(
        'core/src/lamtools_core/plugins/bundled/workflow/ui/index.ts',
      ),
    },
  },
  server: {
    port: 5299,
    strictPort: true,
    fs: { allow: [repo('.')] },
  },
  // The application is large and its own dependency graph is already installed
  // and version-pinned; pre-bundling it again only slows the first frame down.
  optimizeDeps: { include: [] },
}
