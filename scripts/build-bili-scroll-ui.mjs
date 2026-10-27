// user:“不需要 lamtools 重写 就移植原版就行”+(直接静态打包原版 client.js，不使用 eval，也不重画原版组件和 CSS)。
import { readFile, writeFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dependencies = resolve(root, '.build/plugin-rebuild/ui-build/node_modules');
const require = createRequire(resolve(dependencies, '../package.json'));
const { build } = require('esbuild');
const plugin = resolve(root, 'plugins/bili-scroll');
await build({ entryPoints: [resolve(plugin, 'ui/src/original-adapter.mjs')], outfile: resolve(plugin, 'ui/page.mjs'),
  bundle: true, minify: true, format: 'esm', target: 'es2022', nodePaths: [dependencies],
  define: { 'process.env.NODE_ENV': '"production"' }, legalComments: 'eof', plugins: [{
    name: 'unchanged-dsh-client', setup(build) {
      build.onResolve({ filter: /^dsh-original-client$/ }, () => ({ path: 'client', namespace: 'dsh-original' }));
      build.onLoad({ filter: /.*/, namespace: 'dsh-original' }, async () => ({
        contents: 'export function register(window, document, fetch) {\n' + await readFile(resolve(plugin, 'vendor/dsh-client.js'), 'utf8') + '\n}', loader: 'js',
      }));
    },
  }] });
await writeFile(resolve(plugin, 'ui/watched.mjs'), 'export { mountWatched as mount } from "./page.mjs";\n');
console.log('Bundled original DSH 2.2.2 client + React 18.3.1 + host adapter');
