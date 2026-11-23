// 启动 dev 前的端口守卫。
//
// user:“这是因为前端的服务可能被什么东西占了，导致你启动的那个 dev 无法访问，显示 127.0.0.1 无法访问”+
// user:“那就处理掉这个问题”+
// (tauri.conf 的 devUrl 固定 127.0.0.1:5173，但 vite 发现 5173 被占会自动换到 5174——
//  窗口连的还是 5173，于是只显示「127.0.0.1 无法访问」。所以启动前必须先把这个端口腾干净：
//  是本项目上一次残留的 vite 就关掉；是别的程序就明确报错退出，绝不悄悄换端口留个死窗口)。
//
// 只动「命令行里是 vite 且路径属于本仓库」的进程，未知进程一律不杀。

import { execSync } from 'node:child_process'

const PORT = 5173

function pidsListeningOn(port) {
  if (process.platform !== 'win32') return []
  let out = ''
  try {
    out = execSync('netstat -ano -p tcp', { encoding: 'utf8', windowsHide: true })
  } catch {
    return []
  }
  const pids = new Set()
  for (const line of out.split(/\r?\n/)) {
    const parts = line.trim().split(/\s+/)
    if (parts.length < 5) continue
    // 形如 TCP  127.0.0.1:5173  0.0.0.0:0  LISTENING  12345
    const local = parts[1] || ''
    const state = parts[3] || ''
    const pid = parts[4] || ''
    if (state !== 'LISTENING') continue
    if (!local.endsWith(`:${port}`)) continue
    if (/^\d+$/.test(pid)) pids.add(Number(pid))
  }
  return [...pids]
}

function commandLineOf(pid) {
  if (process.platform !== 'win32') return ''
  // 走 -EncodedCommand：cmd 里的引号嵌套很容易把命令本身当结果打印出来，编码一次最省事。
  const script = `$ProgressPreference='SilentlyContinue'; Get-CimInstance Win32_Process -Filter "ProcessId=${pid}" | Select-Object -ExpandProperty CommandLine`
  const encoded = Buffer.from(script, 'utf16le').toString('base64')
  try {
    const out = execSync(`powershell -NoProfile -EncodedCommand ${encoded}`, {
      encoding: 'utf8',
      windowsHide: true,
    })
    return out.trim()
  } catch {
    return ''
  }
}

function killTree(pid) {
  try {
    execSync(`taskkill /PID ${pid} /T /F`, { stdio: 'ignore', windowsHide: true })
    return true
  } catch {
    return false
  }
}

const pids = pidsListeningOn(PORT)
if (pids.length === 0) {
  process.exit(0)
}

let blocked = false
for (const pid of pids) {
  const command = commandLineOf(pid)
  const looksLikeOurVite = /\bvite\b/i.test(command) && /LamTools/i.test(command)
  if (!looksLikeOurVite) {
    blocked = true
    console.error(`[dev] 端口 ${PORT} 被占用，但不是本项目的 vite：PID=${pid}`)
    if (command) console.error(`[dev]   ${command}`)
    console.error('[dev] 请先关掉它再启动；这里不会自动杀未知进程。')
    continue
  }
  console.error(`[dev] 端口 ${PORT} 上有上次残留的 vite（PID=${pid}），先关掉它`)
  if (!killTree(pid)) {
    blocked = true
    console.error(`[dev] 关不掉 PID=${pid}，请手动结束该进程。`)
  }
}

if (blocked) process.exit(1)
process.exit(0)
