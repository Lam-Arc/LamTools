// user:“plugin 'network-exploration' start failed: 缺少 Rust 控制器，请运行 scripts/build-network-controller.ps1 后重启 Sunday”+(控制器 exe 被插件 .gitignore 排除，任何新检出/新工作树都没有它，插件启动时 binary.is_file() 为假就直接抛这句。这里在 Tauri 开发环境启动前按需编译一次，缺了才编，过期才编，已有就直接跳过。)
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, copyFileSync, statSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..', '..');
const pluginDir = path.join(repoRoot, 'core', 'src', 'lamtools_core', 'plugins', 'bundled', 'network-exploration');
const controllerDir = path.join(pluginDir, 'controller');
const binaryName = 'sunday-network-controller.exe';
const target = path.join(pluginDir, 'bin', binaryName);

function log(message) {
  process.stdout.write(`[network-controller] ${message}\n`);
}

function warn(message) {
  process.stderr.write(`[network-controller] ${message}\n`);
}

// 控制器只在 Windows 桌面端编译；没有控制器源码的轻量检出也直接放行。
if (process.platform !== 'win32') process.exit(0);
if (!existsSync(path.join(controllerDir, 'Cargo.toml'))) process.exit(0);

function walkNewestMtime(directory) {
  let newest = 0;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      newest = Math.max(newest, walkNewestMtime(full));
    } else if (entry.isFile()) {
      newest = Math.max(newest, statSync(full).mtimeMs);
    }
  }
  return newest;
}

// 源码/依赖清单比 exe 新，说明这次改动改了控制器，必须重编，避免开发版跑着旧协议。
function newestSourceMtime() {
  let newest = walkNewestMtime(path.join(controllerDir, 'src'));
  for (const name of ['Cargo.toml', 'Cargo.lock']) {
    const file = path.join(controllerDir, name);
    if (existsSync(file)) newest = Math.max(newest, statSync(file).mtimeMs);
  }
  return newest;
}

if (existsSync(target) && statSync(target).mtimeMs >= newestSourceMtime()) {
  process.exit(0);
}

const missing = !existsSync(target);
log(missing ? `缺少 ${binaryName}，编译控制器…` : '控制器源码有更新，重新编译…');

const cargo = spawnSync(
  process.env.CARGO ?? 'cargo',
  [
    'build',
    '--locked',
    '--release',
    '--manifest-path',
    path.join(controllerDir, 'Cargo.toml'),
    '--target-dir',
    path.join(repoRoot, '.build', 'network-controller'),
  ],
  { cwd: controllerDir, stdio: 'inherit', shell: false },
);

if (cargo.error || cargo.status !== 0) {
  warn('控制器编译失败，网络拓展插件本次启动会不可用（其余功能不受影响）。');
  if (cargo.error) warn(String(cargo.error.message ?? cargo.error));
  process.exit(cargo.status ?? 1);
}

const compiled = path.join(repoRoot, '.build', 'network-controller', 'release', binaryName);
if (!existsSync(compiled)) {
  warn(`编译结束但找不到产物：${compiled}`);
  process.exit(1);
}

mkdirSync(path.dirname(target), { recursive: true });
try {
  copyFileSync(compiled, target);
} catch (error) {
  // 旧开发版仍持有该 exe 时 Windows 会拒绝覆盖；留给下次完全重启再替换，不阻塞本次启动。
  warn(`无法写入 ${target}（${error.code ?? error.message}），沿用现有控制器。`);
  if (missing) process.exit(1);
  process.exit(0);
}

log(`已就绪：${target}`);
