// user:“该修就修，不用停下”+(直接编译原版 Markdown 读取函数和压缩解码函数)。
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { readFile } from 'node:fs/promises';
const require = createRequire(resolve('.build/excalidraw-toolchain/package.json'));
const { build } = require('esbuild');
const plugin = resolve('plugins/excalidraw');
const dependencies = resolve('.build/obsidian-excalidraw-upstream/node_modules');
const markdown = await readFile(resolve(plugin, 'vendor/excalidrawMarkdownParsing.ts'), 'utf8');
const scene = await readFile(resolve(plugin, 'vendor/sceneDataUtils.ts'), 'utf8');
const constants = await readFile(resolve(plugin, 'vendor/constants.ts'), 'utf8');
const take = (source, start, end) => {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  if (a < 0 || b < 0) throw Error(`upstream source section missing: ${start}`);
  return source.slice(a, b);
};
const reader = take(markdown, 'const DRAWING_REG =', 'export async function getMarkdownDrawingSectionAsync');
const decompress = take(scene, 'export function decompress(data:', 'export function hasExportTheme');
const compress = take(scene, 'export function compress(data:', 'export async function decompressAsync');
const section = take(markdown, 'export function getMarkdownDrawingSection(', 'const MARKDOWN_IMAGE_OPEN_MARKER');
const frontmatter = take(constants, 'export const FRONTMATTER = [', 'export const EMPTY_MESSAGE');
await build({stdin:{contents:`import LZString from 'lz-string';\ntype RegExpMatchIteratorResult = IteratorResult<RegExpMatchArray, undefined>;\nconst FRONTMATTER_KEYS = { plugin: { name: 'excalidraw-plugin' } };\n${frontmatter}\n${compress}\n${decompress}\n${reader}\n${section}`,resolveDir:dependencies,loader:'ts'},outfile:resolve(plugin,'ui/src/upstream-markdown.mjs'),bundle:true,format:'esm',target:'es2022',minify:false,legalComments:'eof'});
