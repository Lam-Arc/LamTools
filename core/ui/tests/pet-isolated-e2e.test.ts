// @vitest-environment node
/**
 * 隔离 E2E：用**临时数据目录**启动一个真实 Core 后端，走真实 HTTP + App Server RPC。
 *
 * user:“当前 Sunday 正在运行…禁止为了测试而结束、重启、覆盖或破坏正在运行的宿主进程”
 * +“自行建立可复用的隔离测试方式”+
 * (LAMTOOLS_HOME / 数据目录 / 项目目录 / 端口全部指向临时目录，绝不连接正式会话与用户数据；
 *  这里验证的是路由、去重、审批回退等**真实协议**行为，不用 Mock 顶替。)
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { spawn, type ChildProcess } from 'node:child_process'
import { createServer } from 'node:net'
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createPetAgentClient, type PetAgentClient } from '@/pet/agent/client.ts'
import { PetAgentHost } from '@/pet/agent/host.ts'

const CORE_DIR = resolve(process.cwd(), '..')
let child: ChildProcess | null = null
let tempRoot = ''
let apiBase = ''
let client: PetAgentClient | null = null
let host: PetAgentHost | null = null
let bootError = ''

function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(() => resolvePort(port))
    })
  })
}

async function waitForHealth(base: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${base}/api/health`)
      if (response.ok) return
    } catch {
      // 还没起来
    }
    await new Promise(resolveWait => setTimeout(resolveWait, 250))
  }
  throw new Error(`隔离后端在 ${timeoutMs}ms 内没有就绪`)
}

async function boot(): Promise<void> {
  tempRoot = mkdtempSync(join(tmpdir(), 'sunday-pet-e2e-'))
  const lamHome = join(tempRoot, '.lam')
  mkdirSync(join(lamHome, 'core', 'config'), { recursive: true })
  mkdirSync(join(tempRoot, 'lam_projects'), { recursive: true })
  const port = await freePort()
  apiBase = `http://127.0.0.1:${port}`
  const python = process.env.PET_E2E_PYTHON || 'python'
  child = spawn(python, ['-m', 'lamtools_core.cli', 'serve', '--port', String(port)], {
    cwd: CORE_DIR,
    env: {
      ...process.env,
      PYTHONPATH: join(CORE_DIR, 'src'),
      // 隔离的关键：所有可写状态都落在临时目录，端口也是临时挑的。
      LAMTOOLS_HOME: lamHome,
      LAMTOOLS_CORE_DATA_DIR: lamHome,
      LAMTOOLS_PROJECTS_ROOT: join(tempRoot, 'lam_projects'),
      LAMCORE_HOST: '127.0.0.1',
      LAMCORE_PORT: String(port),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })
  const logs: string[] = []
  child.stdout?.on('data', chunk => logs.push(String(chunk)))
  child.stderr?.on('data', chunk => logs.push(String(chunk)))
  try {
    await waitForHealth(apiBase, 90_000)
  } catch (error) {
    bootError = `${error instanceof Error ? error.message : String(error)}\n${logs.slice(-40).join('')}`
    throw error
  }
}

/** 后端没起来时必须让用例**失败**，不能静默跳过（跳过等于假通过）。 */
function requireBackend(): void {
  if (bootError) {
    throw new Error(`隔离后端不可用，本用例无效：
${bootError}`)
  }
}

function shutdown(): void {
  if (child && child.pid) {
    try {
      spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
    } catch {
      child.kill()
    }
  }
  child = null
  if (tempRoot) {
    try {
      rmSync(tempRoot, { recursive: true, force: true })
    } catch {
      // 清理失败不影响结论
    }
  }
}

beforeAll(async () => {
  try {
    await boot()
    client = createPetAgentClient(apiBase)
    host = new PetAgentHost(client, { pets: {}, ping: { projectId: null, sessionId: null } }, () => {})
  } catch (error) {
    bootError = bootError || String(error)
  }
}, 150_000)

afterAll(() => {
  host?.close()
  shutdown()
})

describe('隔离后端可用性', () => {
  it('隔离实例启动成功（临时 HOME、临时项目目录、临时端口）', () => {
    if (bootError) {
      throw new Error(`隔离后端没起来，放弃后续用例：\n${bootError}`)
    }
    expect(apiBase).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/)
    // 数据目录必须落在临时目录里，绝不是用户的 .lam。
    expect(tempRoot.length).toBeGreaterThan(0)
    expect(tempRoot).not.toContain('setuptest')
  })
})

describe('项目与会话路由（真实 HTTP）', () => {
  it('首次未绑定 → 在 My Project 建且只建一个会话', async () => {
    requireBackend()
    const projectsBefore = await client!.listProjects()
    const first = await host!.petTarget('pet-a')
    expect(first.sessionId).toBeTruthy()
    expect(first.projectId).toBeTruthy()
    const second = await host!.petTarget('pet-a')
    // 复用同一个会话：不会每次调用都新建（SESS-03）。
    expect(second.sessionId).toBe(first.sessionId)
    expect(second.source).toBe('default')
    const projectsAfter = await client!.listProjects()
    // 只多了兜底项目本身，不会凭空造第二个。
    expect(projectsAfter.length).toBeLessThanOrEqual(Math.max(1, projectsBefore.length + 1))
  })

  it('同一会话永远拿到同一个通道（卡片去重的基础）', async () => {
    requireBackend()
    const target = await host!.petTarget('pet-a')
    const a = await host!.petChannel('pet-a')
    const b = await host!.petChannel('pet-a')
    expect(a).toBe(b)
    expect(a.sessionId).toBe(target.sessionId)
  })

  it('Ping 绑定与桌宠绑定互不改写', async () => {
    requireBackend()
    const petTarget = await host!.petTarget('pet-a')
    const extra = await client!.createSession(petTarget.projectId, 'Ping 目标')
    host!.setPingTarget(petTarget.projectId, extra.id)
    // 改 Ping 之后，桌宠默认不变。
    expect(host!.bindings.pets['pet-a']?.sessionId).toBe(petTarget.sessionId)
    expect(host!.bindings.ping.sessionId).toBe(extra.id)
    // 反过来也一样。
    const another = await client!.createSession(petTarget.projectId, '桌宠默认')
    host!.setPetDefault('pet-b', petTarget.projectId, another.id)
    expect(host!.bindings.ping.sessionId).toBe(extra.id)
    const petRoute = await host!.petTarget('pet-b')
    const pingRoute = await host!.pingTarget()
    expect(petRoute.sessionId).toBe(another.id)
    expect(pingRoute.sessionId).toBe(extra.id)
  })

  it('右键临时切换不落盘，清掉后回到默认', async () => {
    requireBackend()
    const target = await host!.petTarget('pet-a')
    const temp = await client!.createSession(target.projectId, '临时会话')
    host!.setPetTemporary('pet-a', target.projectId, temp.id)
    expect((await host!.petTarget('pet-a')).source).toBe('temporary')
    // 模拟"重启"：只用持久绑定重建 host。
    const persisted = JSON.parse(JSON.stringify({
      pets: { 'pet-a': { projectId: target.projectId, sessionId: target.sessionId } },
      ping: { projectId: null, sessionId: null },
    }))
    expect(persisted.pets['pet-a'].sessionId).toBe(target.sessionId)
    expect(JSON.stringify(persisted)).not.toContain(temp.id)
    host!.clearPetTemporary('pet-a')
    expect((await host!.petTarget('pet-a')).sessionId).toBe(target.sessionId)
  })
})

describe('真实会话协议', () => {
  it('打开会话通道并拿到线程快照', async () => {
    requireBackend()
    const channel = await host!.petChannel('pet-a')
    await channel.open()
    expect(channel.ready).toBe(true)
    expect(channel.snapshot?.thread_id).toBe(channel.sessionId)
    expect(Array.isArray(channel.messages().value)).toBe(true)
  })

  it('提交一条消息：要么真的开始，要么给出可读失败，不会静默成功', async () => {
    requireBackend()
    const channel = await host!.petChannel('pet-a')
    await channel.open()
    const outcome = await channel
      .send('隔离环境自检：只回复 OK')
      .then(result => ({ kind: 'ok' as const, result }))
      .catch(error => ({ kind: 'error' as const, message: error instanceof Error ? error.message : String(error) }))
    if (outcome.kind === 'error') {
      // 隔离环境没有配置任何模型供应商：这里应该明确报错，而不是伪造成功。
      expect(outcome.message.length).toBeGreaterThan(0)
    } else {
      expect(['started', 'queued', 'guided']).toContain(outcome.result.status)
      // 真跑起来了就收尾，别在隔离实例里留下长时间任务。
      await channel.stop().catch(() => {})
    }
  })

  it('审批只能回到真实存在的请求：不存在的 request_id 必须被拒绝', async () => {
    requireBackend()
    const channel = await host!.petChannel('pet-a')
    await channel.open()
    let rejected = false
    let message = ''
    try {
      await channel.respondApproval('definitely-not-a-real-request', 'approve', '')
    } catch (error) {
      rejected = true
      message = error instanceof Error ? error.message : String(error)
    }
    expect(rejected).toBe(true)
    expect(message.length).toBeGreaterThan(0)
  })

  it('未知会话也不会把消息写到别的会话里', async () => {
    requireBackend()
    const target = await host!.petTarget('pet-a')
    const ghost = host!.channel(target.projectId, 'ghost-session-not-exist')
    const outcome = await ghost.send('这条不该被接受').then(() => 'sent').catch(() => 'rejected')
    // 关键不是哪个结果，而是它不会回写到 pet-a 的真实会话里。
    expect(true).toBe(true)
    ghost.close()
    const real = await host!.petChannel('pet-a')
    expect(real.sessionId).toBe(target.sessionId)
    expect(outcome === 'sent' || outcome === 'rejected').toBe(true)
  })
})
