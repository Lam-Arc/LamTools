#!/usr/bin/env node
/**
 * 桌宠开发实例启动器。
 *
 * user:“你给开发版改一下端口吧”+“打开桌宠你用 cli”+
 * (固定 vite 5299 / 后端 5298、独立数据目录 .lam-petdev，并用 --open-pet 直接开覆盖层，
 *  这样开发实例和正式 Sunday 以及其它开发服务器都不会互抢端口、互锁数据库。)
 */
import { spawn } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const desktopDir = join(here, '..')
const repoRoot = join(desktopDir, '..', '..')

const env = {
  ...process.env,
  // 独立数据目录：配置、数据库、项目都落在仓库根的 .lam-petdev。
  // 应用与后端子进程共用同一个隔离数据目录（桌宠配置也落在这里）。
  LAMTOOLS_HOME: join(repoRoot, '.lam-petdev'),
  LAMTOOLS_PET_DEV_HOME: join(repoRoot, '.lam-petdev'),
  // 固定后端端口，被占时才自动回退。
  LAMTOOLS_DEV_BACKEND_PORT: process.env.LAMTOOLS_DEV_BACKEND_PORT || '5298',
  // user:"未响应"+(后端的消息来源白名单只认 5172/5173/5180，pet-dev 的前端在
  // 5299，WebSocket 被按跨站 403 拒绝，整个界面等于断网。这里把 5299 加进
  // 后端预留的白名单扩展环境变量，只作用于开发实例。)
  LAMTOOLS_CORE_ALLOWED_ORIGINS: 'http://127.0.0.1:5299,http://localhost:5299',
  // 用环境变量让应用在启动后直接开桌宠：tauri dev 的 `--` 参数会被塞给 cargo。
  SUNDAY_PET_OPEN: process.argv.includes('--no-open') ? '0' : '1',
}

const args = ['tauri', 'dev', '--config', 'tauri.pet-dev.conf.json']

console.log(`[pet:dev] vite=http://127.0.0.1:5299 backend=${env.LAMTOOLS_DEV_BACKEND_PORT} home=${env.LAMTOOLS_PET_DEV_HOME}`)

// Windows 下 npx 是 .cmd，Node 20+ 不允许直接 spawn（EINVAL），必须经 cmd /c。
const child = process.platform === 'win32'
  ? spawn('cmd.exe', ['/c', 'npx', ...args], { cwd: desktopDir, env, stdio: 'inherit' })
  : spawn('npx', args, { cwd: desktopDir, env, stdio: 'inherit' })

child.on('exit', code => process.exit(code ?? 0))
child.on('error', error => {
  console.error('[pet:dev] failed to start:', error)
  process.exit(1)
})
