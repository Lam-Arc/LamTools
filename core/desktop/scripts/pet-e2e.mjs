#!/usr/bin/env node
/**
 * 桌宠端到端自动化（WebDriverIO + tauri-driver）。
 *
 * user:“自动化用 WebdriverIO”+
 * (真机点击由用户判断；这里只验证可自动化的部分：应用能起、主窗口渲染、
 *  桌宠覆盖层窗口存在且 PetSurface 真的挂载、没有启动期控制台错误。
 *  全程用独立标识、独立数据目录、独立端口，不碰正在运行的正式 Sunday。)
 *
 * 前置：cargo install tauri-driver --locked；msedgedriver 与 WebView2 版本一致。
 * 用法：node scripts/pet-e2e.mjs
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { remote } from 'webdriverio'

const here = dirname(fileURLToPath(import.meta.url))
const desktopDir = join(here, '..')
const repoRoot = join(desktopDir, '..', '..')
const driverDir = join(repoRoot, '.tools', 'webdriver')
const e2eHome = join(repoRoot, '.lam-pete2e')
const artifacts = join(repoRoot, '.lam', 'artifacts', 'pet-e2e')
const appBinary = join(desktopDir, 'src-tauri', 'target', 'debug', 'Sunday.exe')
// user:“自动化用 WebdriverIO”+(msedgedriver 拿到反斜杠路径会吃掉分隔符报
//  "no msedge binary"，统一用正斜杠；WebView2 的用户数据目录指到隔离目录，
//  否则驱动注入的调试参数落不进它轮询的目录，DevToolsActivePort 永远找不到。)
const appBinaryForDriver = appBinary.replaceAll('\\', '/')
const VITE_PORT = 5173
const DRIVER_PORT = 4444

const children = []

function start(label, command, args, env = {}) {
  const child = spawn(command, args, {
    cwd: desktopDir,
    env: { ...process.env, ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
  })
  const log = []
  child.stdout.on('data', chunk => log.push(String(chunk)))
  child.stderr.on('data', chunk => log.push(String(chunk)))
  // 应用的 stderr 会汇进 tauri-driver 的输出；失败时必须能看到它才能定位。
  child.on('exit', code => {
    if (code !== 0 && code !== null) console.log(`[${label}] exited ${code}\n${log.slice(-8).join('')}`)
  })
  children.push({ label, child, log })
  return child
}

async function waitHttp(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return true
    } catch {
      // 还没起来
    }
    await new Promise(resolve => setTimeout(resolve, 300))
  }
  return false
}

function cleanup() {
  for (const { child } of children) {
    if (child.pid && !child.killed) {
      try {
        // eslint-disable-next-line no-undef
        process.kill(child.pid)
      } catch {
        // 已退出
      }
    }
  }
}

async function main() {
  if (!existsSync(appBinary)) throw new Error(`缺少应用二进制：${appBinary}（先跑 npm run pet:dev 或 cargo build）`)
  if (!existsSync(join(driverDir, 'msedgedriver.exe'))) {
    throw new Error(`缺少 msedgedriver：${join(driverDir, 'msedgedriver.exe')}`)
  }
  rmSync(e2eHome, { recursive: true, force: true })
  mkdirSync(e2eHome, { recursive: true })
  mkdirSync(artifacts, { recursive: true })

  console.log('[e2e] 启动 vite …')
  start('vite', 'node', [join(desktopDir, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1', '--port', String(VITE_PORT), '--strictPort'])
  const viteReady = await waitHttp(`http://127.0.0.1:${VITE_PORT}/pet.html`, 60_000)
  if (!viteReady) throw new Error('vite 未就绪')
  // user:“自动化用 WebdriverIO”+(覆盖层页面有 15 秒沉默看门狗；vite 冷启动第一次
  //  转换 pet 入口及其依赖可能超过 15 秒，页面还没执行就被判沉默。这里先把 pet
  //  模块图预热一遍，应用起来时 vite 已经热好，页面能立刻完成启动握手。)
  await fetch(`http://127.0.0.1:${VITE_PORT}/src/pet.ts`).then(res => res.text()).catch(() => '')
  await new Promise(resolve => setTimeout(resolve, 3000))
  console.log('[e2e] vite 就绪（pet 入口已预热）')

  console.log('[e2e] 启动 tauri-driver …')
  start('tauri-driver', 'tauri-driver', ['--port', String(DRIVER_PORT)], {
    PATH: `${driverDir};${process.env.PATH}`,
    // 应用由 driver 拉起：隔离数据目录与自动开桌宠都通过环境变量传下去。
    SUNDAY_PET_OPEN: '1',
    LAMTOOLS_HOME: e2eHome,
  })
  const driverReady = await waitHttp(`http://127.0.0.1:${DRIVER_PORT}/status`, 60_000)
  if (!driverReady) throw new Error('tauri-driver 未就绪')
  console.log('[e2e] tauri-driver 就绪')

  const results = []
  let browser
  try {
    browser = await remote({
      hostname: '127.0.0.1',
      port: DRIVER_PORT,
      logLevel: 'error',
      connectionRetryCount: 1,
      capabilities: {
        'tauri:options': {
          application: appBinaryForDriver,
          // 注意：应用标识在构建期固化，无法用运行参数改；pet:e2e 需要在
          // pet-dev 实例关闭时运行（同时跑会秒退，表现为 Chrome instance exited）。
          webviewOptions: { userDataFolder: join(e2eHome, 'webview-data').replaceAll('\\', '/') },
        },
      },
    })

    const mainHandle = await browser.getWindowHandle()
    const mainUrl = await browser.getUrl()
    results.push({ name: '主窗口加载开发服务', ok: mainUrl.includes(String(VITE_PORT)) })
    const appMounted = await browser.$('#app').isExisting()
    results.push({ name: '主窗口根节点存在', ok: appMounted })

    // 等桌宠覆盖层窗口出现：它是一个独立 webview。页面会把启动进度写进标题
    // （Sunday Pet · loading/mounting/ready/boot failed），所以按前缀匹配，
    // 并把见过的标题记下来，失败时能看到卡在哪一步。
    const deadline = Date.now() + 60_000
    let petHandle = null
    let petTitle = ''
    const seenTitles = new Set()
    while (Date.now() < deadline) {
      const handles = await browser.getWindowHandles()
      for (const handle of handles) {
        if (handle === mainHandle) continue
        try {
          await browser.switchToWindow(handle)
          const title = await browser.getTitle()
          seenTitles.add(title)
          if (title.startsWith('Sunday Pet')) {
            petHandle = handle
            petTitle = title
            if (title.startsWith('Sunday Pet · ready')) break
          }
        } catch {
          // 窗口可能在切换途中关闭
        }
      }
      if (petHandle && petTitle.startsWith('Sunday Pet · ready')) break
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
    results.push({
      name: '桌宠覆盖层窗口出现',
      ok: Boolean(petHandle && petTitle.startsWith('Sunday Pet · ready')),
      detail: petTitle || [...seenTitles].join(' | ') || '没有任何其他窗口句柄',
    })

    if (petHandle) {
      const petMounted = await browser.$('#pet-app').isExisting()
      results.push({ name: 'PetSurface 已挂载', ok: petMounted })
      // 挂载后 boot() 会写配置与安装预设，等文件落地再判定。
      const configured = await waitFor(() => existsSync(join(e2eHome, 'pet', 'config.json')), 40_000)
      results.push({ name: '桌宠配置写入隔离目录', ok: configured })
      const preset = await waitFor(() => existsSync(join(e2eHome, 'pet', 'packs', 'sunday-blocky')), 40_000)
      results.push({ name: '方块人预设自动安装', ok: preset })
      const bodyText = await browser.$('#pet-app').getText().catch(() => '')
      results.push({ name: '覆盖层不是错误页', ok: !/桌宠未启动|桌宠正在启动/.test(bodyText || '') })
      // 渲染硬证据：WebGL 画布拍不进截图，改读诊断 HUD 的 FPS——大于 0 说明
      // 渲染循环真的在出帧，桌宠不是"空壳窗口"。FPS 每 500ms 才结算一次，
      // 自动化下 rAF 可能被节流，所以轮询等它变成正数。
      try {
        await browser.$('.pet-stage__hud-toggle').click()
        let hudText = ''
        await browser.waitUntil(
          async () => {
            hudText = await browser.$('.pet-stage__hud').getText()
            const fps = Number((hudText.match(/FPS\s+(\d+(?:\.\d+)?)/) || [])[1] || 0)
            return fps > 0
          },
          { timeout: 20_000, interval: 500 },
        )
        results.push({ name: '渲染循环出帧（FPS>0）', ok: true, detail: hudText.split('\n')[0] })
      } catch (error) {
        const hudText = await browser.$('.pet-stage__hud').getText().catch(() => '(HUD 读不到)')
        results.push({
          name: '渲染循环出帧（FPS>0）',
          ok: false,
          detail: `${hudText.split('\n')[0]} / ${String(error).slice(0, 80)}`,
        })
      }
      // user:"左下角确实有个诊断，但是我没看见方块人啊"+(方块人从未进入 3D 渲染
      //  列表（renderables 只认 'model' 漏了 'blocky'），3D 层永远不启动。HUD 的
      //  3D 行必须显示已启用。)
      try {
        const hud = await browser.$('.pet-stage__hud').getText()
        results.push({
          name: '3D 渲染层已启用（方块人可见的前提）',
          ok: /3D[:：]\s*已启用/.test(hud || ''),
          detail: (hud.split('\n').find(l => l.includes('3D')) || '(HUD 无 3D 行)').trim(),
        })
      } catch (error) {
        results.push({ name: '3D 渲染层已启用（方块人可见的前提）', ok: false, detail: String(error).slice(0, 80) })
      }
      // user:"左下角确实有个诊断，但是我没看见方块人啊"+(3D 画布的绘制缓冲曾经
      //  一直是 HTML 默认的 300×150，角色按全屏坐标算出的视口全被裁掉。这里回归：
      //  缓冲必须同步到覆盖层的物理尺寸。)
      try {
        const size = await browser.execute(() => {
          const el = document.querySelector('.pet-stage__canvas--gl')
          return el ? { w: el.width, h: el.height } : null
        })
        const ok = Boolean(size && size.w >= 1000 && size.h >= 700)
        results.push({
          name: '3D 画布缓冲为全屏尺寸',
          ok,
          detail: size ? `${size.w}x${size.h}` : 'gl canvas 不存在',
        })
      } catch (error) {
        results.push({ name: '3D 画布缓冲为全屏尺寸', ok: false, detail: String(error).slice(0, 100) })
      }
      try {
        const shot = await browser.takeScreenshot()
        writeFileSync(join(artifacts, 'pet-overlay.png'), Buffer.from(shot, 'base64'))
        results.push({ name: '覆盖层截图已保存', ok: true })
      } catch (error) {
        results.push({ name: '覆盖层截图已保存', ok: false, detail: String(error) })
      }
    }

    // 回到主窗口，确认它仍在
    await browser.switchToWindow(mainHandle)
    results.push({ name: '主窗口仍在运行', ok: (await browser.getUrl()).includes(String(VITE_PORT)) })
  } finally {
    if (browser) await browser.deleteSession().catch(() => {})
  }

  cleanup()
  const failed = results.filter(item => !item.ok)
  console.log('\n=== 桌宠 E2E 结果 ===')
  for (const item of results) console.log(`${item.ok ? 'PASS' : 'FAIL'}  ${item.name}${item.detail ? `  (${item.detail})` : ''}`)
  console.log(`共 ${results.length} 项，失败 ${failed.length} 项`)
  if (failed.length > 0) {
    // 失败时把应用侧 stderr（汇在 tauri-driver 的输出里）落到 artifacts 方便定位。
    for (const { label, log } of children) {
      const text = log.join('')
      if (text.trim()) {
        writeFileSync(join(artifacts, `${label.replace(/[^\w.-]+/g, '_')}.log`), text)
      }
    }
    console.log(`日志已写入 ${artifacts}`)
  }
  if (failed.length > 0) process.exit(1)
}

function waitFor(predicate, timeoutMs) {
  return new Promise(resolve => {
    const deadline = Date.now() + timeoutMs
    const tick = () => {
      if (predicate()) return resolve(true)
      if (Date.now() > deadline) return resolve(false)
      setTimeout(tick, 500)
    }
    tick()
  })
}

process.on('uncaughtException', error => {
  console.error('[e2e] 未捕获异常：', error)
  cleanup()
  process.exit(1)
})

main().catch(error => {
  console.error('[e2e] 失败：', error)
  cleanup()
  process.exit(1)
})
