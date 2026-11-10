/**
 * 桌宠实时性修复验收。
 *
 * user:“第 1 点就是我怀疑桌宠的建图并不是实时去建的，而是只在桌宠启动后去建，
 * 第 2 点就是当一个会话结束后，桌宠上面并没有触发通知，也没有触发审批”
 *
 * 三块：
 *  1. 建图：窗口几何指纹去重 + 刷新节奏不再跟 zMode 绑死（源码契约）。
 *  2. 通知：回合“活跃 → 终态”的迁移判定，以及按 config.bubbles.done 生成气泡。
 *  3. 审批：通道打不开时按退避自动重开，不再是永久静默的死通道。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { windowFingerprint } from '../src/pet/engine/windows.ts'
import { TurnNoticeTracker, turnNoticeBubble } from '../src/pet/agent/turnNotice.ts'
import { SessionChannel } from '../src/pet/agent/host.ts'
import { parseAllSessions, pickLatestPetSession, type PetProjectSession } from '../src/pet/agent/client.ts'
import { resolveWatchPet, SessionWatcher } from '../src/pet/agent/sessionWatch.ts'
import type { PetAgentClient } from '../src/pet/agent/client.ts'
import type { DesktopWindow } from '../src/pet/engine/terrain.ts'
import type { LamToolsTransport, TransportConnectionState, TransportMessage, TransportRequest } from '../src/transport/types'

const uiRoot = resolve(import.meta.dirname, '../src')

function windowAt(id: string, x: number, y: number, z: number, width = 800, height = 600): DesktopWindow {
  return {
    id,
    title: id,
    className: 'Test',
    bounds: { x, y, width, height },
    z,
  }
}

// ---------------------------------------------------------------------------
// 1. 建图：只有窗口几何真的变了才重建
// ---------------------------------------------------------------------------
describe('窗口几何指纹（建图去重）', () => {
  it('同一份窗口重复枚举得到同一指纹', () => {
    const first = [windowAt('a', 10, 20, 0), windowAt('b', 300, 400, 1)]
    const second = [windowAt('a', 10, 20, 0), windowAt('b', 300, 400, 1)]
    expect(windowFingerprint(first)).toBe(windowFingerprint(second))
  })

  it('窗口移动、开新窗、关窗都会改变指纹', () => {
    const base = [windowAt('a', 10, 20, 0)]
    expect(windowFingerprint([windowAt('a', 11, 20, 0)])).not.toBe(windowFingerprint(base))
    expect(windowFingerprint([windowAt('a', 10, 20, 0), windowAt('b', 0, 0, 1)])).not.toBe(windowFingerprint(base))
    expect(windowFingerprint([])).not.toBe(windowFingerprint(base))
  })

  it('层级变化也算变化（L2 可见性裁剪依赖 z 序）', () => {
    const before = [windowAt('a', 0, 0, 0), windowAt('b', 100, 100, 1)]
    const after = [windowAt('a', 0, 0, 1), windowAt('b', 100, 100, 0)]
    expect(windowFingerprint(after)).not.toBe(windowFingerprint(before))
  })

  it('亚像素级的抖动按整数像素归一，不触发重建', () => {
    const before = [windowAt('a', 10.2, 20.4, 0)]
    const after = [windowAt('a', 10.4, 20.2, 0)]
    expect(windowFingerprint(after)).toBe(windowFingerprint(before))
  })
})

// ---------------------------------------------------------------------------
// 2. 通知：回合结束才通知，且不把历史任务当成刚完成
// ---------------------------------------------------------------------------
describe('回合终态通知', () => {
  it('第一次看到某个会话只记状态，不补发历史通知', () => {
    const tracker = new TurnNoticeTracker()
    expect(tracker.observe('s1', 'completed')).toBeNull()
    expect(tracker.observe('s1', 'running')).toBeNull()
  })

  it('活跃 → 完成 / 失败 / 停止 各出一次通知', () => {
    const tracker = new TurnNoticeTracker()
    tracker.observe('s1', 'running')
    expect(tracker.observe('s1', 'completed')).toEqual(expect.objectContaining({ status: 'completed', title: '任务完成' }))

    const failed = new TurnNoticeTracker()
    failed.observe('s2', 'waiting')
    expect(failed.observe('s2', 'failed')).toEqual(expect.objectContaining({ status: 'failed' }))

    const stopped = new TurnNoticeTracker()
    stopped.observe('s3', 'interrupting')
    expect(stopped.observe('s3', 'cancelled')).toEqual(expect.objectContaining({ status: 'cancelled' }))
  })

  it('终态之间的重复读数不会重复通知', () => {
    const tracker = new TurnNoticeTracker()
    tracker.observe('s1', 'running')
    expect(tracker.observe('s1', 'completed')).not.toBeNull()
    expect(tracker.observe('s1', 'completed')).toBeNull()
    expect(tracker.observe('s1', 'idle')).toBeNull()
  })

  it('什么都没跑过就变成终态不通知', () => {
    const tracker = new TurnNoticeTracker()
    tracker.observe('s1', 'idle')
    expect(tracker.observe('s1', 'completed')).toBeNull()
  })

  it('两个会话的状态互不覆盖', () => {
    const tracker = new TurnNoticeTracker()
    tracker.observe('a', 'running')
    tracker.observe('b', 'idle')
    expect(tracker.observe('b', 'completed')).toBeNull()
    expect(tracker.observe('a', 'completed')).not.toBeNull()
  })
})

describe('通知气泡策略', () => {
  const notice = { status: 'completed' as const, title: '任务完成', body: '本轮任务已结束' }

  it('弹出：展开卡片且编号带会话与状态', () => {
    const bubble = turnNoticeBubble('s1', notice, 'popup', 1000)
    expect(bubble).toEqual(expect.objectContaining({ kind: 'notification', expanded: true, title: '任务完成' }))
    expect(bubble?.id).toContain('s1')
    expect(bubble?.id).toContain('completed')
  })

  it('标记：折叠气泡', () => {
    expect(turnNoticeBubble('s1', notice, 'badge', 1000)).toEqual(expect.objectContaining({ expanded: false }))
  })

  it('静默：完全不出气泡', () => {
    expect(turnNoticeBubble('s1', notice, 'silent', 1000)).toBeNull()
  })

  it('同一会话连跑两轮是两条通知，不会被去重吃掉', () => {
    const first = turnNoticeBubble('s1', notice, 'popup', 1000)
    const second = turnNoticeBubble('s1', notice, 'popup', 2000)
    expect(first?.id).not.toBe(second?.id)
  })
})

// ---------------------------------------------------------------------------
// 3. 审批：通道打不开要重试，而不是永久静默
// ---------------------------------------------------------------------------
class FlakyTransport implements LamToolsTransport {
  connectCalls = 0
  private failuresLeft = 1
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()

  async connect(): Promise<void> {
    this.connectCalls += 1
    if (this.failuresLeft > 0) {
      this.failuresLeft -= 1
      throw new Error('backend not ready')
    }
    for (const listener of this.stateListeners) listener('connected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    if (request.kind === 'http') return { status: 200, headers: {}, body: new Uint8Array() } as TResponse
    if (request.method === 'initialize') return { capabilities: {} } as TResponse
    return {} as TResponse
  }

  send(): void {}
  subscribe(_listener: (message: TransportMessage) => void): () => void { return () => {} }
  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    return () => { this.stateListeners.delete(listener) }
  }
  close(): void {}
  getState(): TransportConnectionState { return 'connected' }
}

function makeClient(transport: LamToolsTransport): PetAgentClient {
  return {
    apiBase: 'http://pet.test',
    transport: { fork: () => transport } as unknown as PetAgentClient['transport'],
    projects: {} as never,
    listSessions: async () => [],
    createSession: async () => ({ id: 's1', title: 't', projectId: 'p1' }),
    ensureFallbackSession: async () => ({ projectId: 'p1', sessionId: 's1', created: true }),
    ensurePingSession: async () => ({ projectId: 'p1', sessionId: 'ping', created: true }),
    ensureProjectSession: async () => ({ projectId: 'p1', sessionId: 's1', created: false }),
    uploadScreenshot: async () => ({ id: 'a1', path: '/x.png', filename: 'x.png', mimeType: 'image/png', size: 1 }),
    attachmentInput: (upload: { id: string }) => ({ type: 'attachment', attachment_id: upload.id }),
    close: () => {},
  } as unknown as PetAgentClient
}

describe('SessionChannel 打开失败后按退避重试', () => {
  let channel: SessionChannel | null = null

  afterEach(() => {
    channel?.close()
    channel = null
  })

  it('首次失败返回 false，退避窗口内不重复打后端，窗口过后能重开', async () => {
    const transport = new FlakyTransport()
    channel = new SessionChannel(makeClient(transport), { sessionId: 's1', projectId: 'p1' })

    expect(await channel.ensureReady(1000)).toBe(false)
    expect(channel.lastError).toContain('backend not ready')
    expect(transport.connectCalls).toBe(1)

    // 退避窗口内：不再打后端。
    expect(await channel.ensureReady(1500)).toBe(false)
    expect(transport.connectCalls).toBe(1)

    // 窗口过后：第二次连接成功，通道打通（快照由后续轮询再等）。
    const reopened = await channel.ensureReady(4100)
    expect({ reopened, error: channel.lastError, calls: transport.connectCalls }).toEqual({ reopened: true, error: '', calls: 2 })

    // 已打通后不再重复连接。
    expect(await channel.ensureReady(9000)).toBe(true)
    expect(transport.connectCalls).toBe(2)
  })
})

// ---------------------------------------------------------------------------
// 4. 装配契约：刷新不再跟 zMode 绑死，轮询接上通知与重试
// ---------------------------------------------------------------------------
describe('桌宠运行时接上了实时建图与通知', () => {
  const runtimeSource = () => readFileSync(resolve(uiRoot, 'pet/ui/usePetRuntime.ts'), 'utf8')

  it('窗口刷新按固定节奏跑，不再只在 clip 遮挡模式下刷新', () => {
    const source = runtimeSource()
    expect(source).not.toContain("config.zMode === 'clip' && now - lastWindowsAt")
    expect(source).toContain('WINDOW_REFRESH_MS')
    expect(source).toContain('windowFingerprint')
  })

  it('启动时强制建一次图，手动刷新地形也会重建窗口地形', () => {
    const source = runtimeSource()
    expect(source).toContain('await refreshWindows(true)')
    expect(source).toContain('refreshWindows(true); void refreshL3()')
  })

  it('轮询里接上回合终态判定与通知气泡', () => {
    const source = runtimeSource()
    expect(source).toContain("from '../agent/turnNotice.ts'")
    expect(source).toContain('turnNotices.observe(sessionId')
    expect(source).toContain('config.bubbles.done')
  })

  it('通道没就绪时自动重开，并把错误暴露出来', () => {
    const source = runtimeSource()
    expect(source).toContain('channel.ensureReady()')
    expect(source).toContain('通道未就绪')
    const host = readFileSync(resolve(uiRoot, 'pet/agent/host.ts'), 'utf8')
    expect(host).toContain('async ensureReady(now = Date.now())')
  })

  it('桌宠启动就建立默认监听会话，不再依赖用户手选', () => {
    expect(runtimeSource()).toContain('void ensurePetSession(record.id)')
  })
})

// ---------------------------------------------------------------------------
// 5. 默认监听会话：挑最近活动的普通会话
// ---------------------------------------------------------------------------
describe('默认监听会话的选择', () => {
  const session = (id: string, updatedAt?: string | number, internal = false): PetProjectSession => ({
    id,
    title: id,
    projectId: 'p1',
    updatedAt,
    internal,
  })

  it('按最近更新时间挑，不看后端返回顺序', () => {
    const picked = pickLatestPetSession([
      session('old', '2026-01-01T00:00:00Z'),
      session('newest', '2026-03-01T00:00:00Z'),
      session('middle', 1770000000000),
    ])
    expect(picked?.id).toBe('newest')
  })

  it('毫秒时间戳同样参与比较', () => {
    const picked = pickLatestPetSession([
      session('iso', '2026-01-01T00:00:00Z'),
      session('ms', Date.parse('2026-05-01T00:00:00Z')),
    ])
    expect(picked?.id).toBe('ms')
  })

  it('跳过插件与内部编排会话', () => {
    const picked = pickLatestPetSession([
      session('workflow', '2026-09-01T00:00:00Z', true),
      session('normal', '2026-02-01T00:00:00Z'),
    ])
    expect(picked?.id).toBe('normal')
  })

  it('全是内部会话时返回空，由调用方新建一个普通会话', () => {
    expect(pickLatestPetSession([session('a', undefined, true)])).toBeUndefined()
    expect(pickLatestPetSession([])).toBeUndefined()
  })

  it('没有更新时间时退回第一个候选，不会绑成空', () => {
    expect(pickLatestPetSession([session('a'), session('b')])?.id).toBe('a')
  })
})

// ---------------------------------------------------------------------------
// 6. 通知可见性：主界面聚焦时审批让位，回合结束通知仍要露出来
// ---------------------------------------------------------------------------
describe('气泡可见性', () => {
  it('主窗口聚焦时只保留回合结束通知，审批/提问照旧让位', () => {
    const source = readFileSync(resolve(uiRoot, 'pet/ui/PetBubbles.vue'), 'utf8')
    expect(source).toContain('runtime.mainFocused')
    expect(source).toContain("bubble.kind === 'notification'")
    expect(source).not.toContain('!hidden')
  })

  it('任务完成按 config.bubbles.done 呈现（弹出展开，标记折叠）', () => {
    const source = readFileSync(resolve(uiRoot, 'pet/ui/PetBubbles.vue'), 'utf8')
    expect(source).toContain("value.kind === 'notification'")
    expect(source).toContain('ui.expanded = value.expanded')
  })
})

// ---------------------------------------------------------------------------
// 7. 盯所有会话：完成通知与订阅计划
// ---------------------------------------------------------------------------
const ws = (id: string, status: string, updatedAt = 0, internal = false): PetProjectSession => ({
  id,
  title: `会话 ${id}`,
  projectId: 'p1',
  updatedAt,
  status,
  internal,
})

const noExtra = { bound: new Set<string>(), pending: new Set<string>() }

describe('会话守望：所有会话的完成通知', () => {
  it('第一次看到落定状态不通知，不把历史任务当成刚完成', () => {
    const watcher = new SessionWatcher()
    const plan = watcher.observe([ws('a', 'completed')], { now: 1000, ...noExtra })
    expect(plan.finished).toHaveLength(0)
  })

  it('忙 → 完成弹一次，同一份状态不会重复', () => {
    const watcher = new SessionWatcher()
    watcher.observe([ws('a', 'running')], { now: 1000, ...noExtra })
    const plan = watcher.observe([ws('a', 'completed')], { now: 4000, ...noExtra })
    expect(plan.finished.map(session => session.id)).toEqual(['a'])
    expect(watcher.observe([ws('a', 'completed')], { now: 7000, ...noExtra }).finished).toHaveLength(0)
  })

  it('失败要通知，用户自己停的不通知', () => {
    const failed = new SessionWatcher()
    failed.observe([ws('a', 'running')], { now: 1000, ...noExtra })
    expect(failed.observe([ws('a', 'failed')], { now: 4000, ...noExtra }).finished).toHaveLength(1)

    const stopped = new SessionWatcher()
    stopped.observe([ws('b', 'running')], { now: 1000, ...noExtra })
    expect(stopped.observe([ws('b', 'cancelled')], { now: 4000, ...noExtra }).finished).toHaveLength(0)
  })

  it('插件与内部编排会话不参与守望', () => {
    const watcher = new SessionWatcher()
    watcher.observe([ws('workflow:x', 'running', 0, true)], { now: 1000, ...noExtra })
    const plan = watcher.observe([ws('workflow:x', 'completed', 0, true)], { now: 4000, ...noExtra })
    expect(plan.finished).toHaveLength(0)
    expect(plan.subscribe).toHaveLength(0)
  })

  it('会话消失后状态被清掉，重新出现不误判', () => {
    const watcher = new SessionWatcher()
    watcher.observe([ws('a', 'running')], { now: 1000, ...noExtra })
    watcher.observe([], { now: 2000, ...noExtra })
    expect(watcher.size()).toBe(0)
    expect(watcher.observe([ws('a', 'completed')], { now: 3000, ...noExtra }).finished).toHaveLength(0)
  })
})

describe('会话守望：订阅集合与上限', () => {
  it('只订阅忙的、绑定到桌宠的、和挂着气泡的会话', () => {
    const watcher = new SessionWatcher()
    const plan = watcher.observe(
      [ws('busy', 'running'), ws('idle', 'completed'), ws('bound', 'idle'), ws('bubbled', 'completed')],
      { now: 1000, bound: new Set(['bound']), pending: new Set(['bubbled']) },
    )
    expect(plan.subscribe.map(session => session.id).sort()).toEqual(['bound', 'bubbled', 'busy'])
  })

  it('超上限时绑定会话永不被挤掉，忙的按最近活动优先', () => {
    const watcher = new SessionWatcher()
    const busy = Array.from({ length: 12 }, (_, index) => ws(`b${String(index).padStart(2, '0')}`, 'running', 1000 + index))
    const plan = watcher.observe([ws('bound', 'completed'), ...busy], {
      now: 2000,
      bound: new Set(['bound']),
      pending: new Set(),
      maxChannels: 3,
    })
    expect(plan.subscribe).toHaveLength(3)
    expect(plan.subscribe[0].id).toBe('bound')
    expect(plan.subscribe.slice(1).map(session => session.id)).toEqual(['b11', 'b10'])
    expect(plan.dropped).toBeGreaterThan(0)
  })

  it('落定后宽限期继续订阅，过期就释放', () => {
    const watcher = new SessionWatcher()
    const options = { ...noExtra, settledGraceMs: 60_000 }
    watcher.observe([ws('a', 'running')], { now: 0, ...options })
    watcher.observe([ws('a', 'completed')], { now: 1000, ...options })
    expect(watcher.observe([ws('a', 'completed')], { now: 30_000, ...options }).subscribe.map(s => s.id)).toEqual(['a'])
    expect(watcher.observe([ws('a', 'completed')], { now: 120_000, ...options }).subscribe).toHaveLength(0)
  })

  it('忙的会话一定订阅；历史落定会话不占通道', () => {
    const watcher = new SessionWatcher()
    const plan = watcher.observe([ws('a', 'running'), ws('old', 'completed')], { now: 1000, ...noExtra })
    expect(plan.subscribe.map(session => session.id)).toEqual(['a'])
  })
})

describe('通知落在哪只宠物', () => {
  const pets = [{ id: 'p1', visible: true }, { id: 'p2', visible: false }]

  it('优先该会话绑定的那只，临时绑定也算', () => {
    expect(resolveWatchPet({ p2: { sessionId: 's9' } }, pets, 's9')).toBe('p2')
    expect(resolveWatchPet({ p2: { temporarySessionId: 's8' } }, pets, 's8')).toBe('p2')
  })

  it('没绑定就用第一只可见的', () => {
    expect(resolveWatchPet({}, pets, 's1')).toBe('p1')
  })

  it('一只宠物都没有就返回空，由调用方决定不出气泡', () => {
    expect(resolveWatchPet({}, [], 's1')).toBe('')
  })
})

describe('全局会话列表解析', () => {
  it('裸数组与 { sessions } 两种外形都认', () => {
    expect(parseAllSessions('[{"id":"s1"}]').map(s => s.id)).toEqual(['s1'])
    expect(parseAllSessions('{"sessions":[{"id":"s2"}]}').map(s => s.id)).toEqual(['s2'])
  })

  it('映射状态、项目、工作根与内部会话', () => {
    const list = parseAllSessions(JSON.stringify([
      { id: 's1', title: '任务', status: 'running', project_id: 'p1', updated_at: '2026-01-01T00:00:00Z', metadata: { work_root: 'E:/w' } },
      { id: 'workflow:abc', title: '插件', status: 'idle', metadata: { owner_plugin: 'bili' } },
      { id: 's3', title: '驼峰', status: 'idle', updatedAt: '2026-02-02T00:00:00Z' },
    ]))
    expect(list[0]).toEqual(expect.objectContaining({
      id: 's1', projectId: 'p1', status: 'running', workRoot: 'E:/w', internal: false,
    }))
    expect(list[1].internal).toBe(true)
    expect(list[2].updatedAt).toBe('2026-02-02T00:00:00Z')
  })

  it('解析失败抛错，不当成空列表去拆订阅', () => {
    expect(() => parseAllSessions('not json')).toThrow()
  })
})

// ---------------------------------------------------------------------------
// 8. 装配契约：审批轮询走通道，通知两条来源共用一份去重
// ---------------------------------------------------------------------------
describe('桌宠守望接入运行时', () => {
  const runtimeSource = () => readFileSync(resolve(uiRoot, 'pet/ui/usePetRuntime.ts'), 'utf8')
  const pollSource = () => {
    const text = runtimeSource()
    const start = text.indexOf('function pollAgentEvents')
    const end = text.indexOf('// 交互', start)
    return text.slice(start, end)
  }

  it('启动即发现并定时同步所有会话', () => {
    const source = runtimeSource()
    expect(source).toContain('listAllSessions')
    expect(source).toContain('void discoverSessions()')
    expect(source).toContain('WATCH_DISCOVERY_MS')
  })

  it('审批轮询遍历已订阅通道，不再按宠物绑定逐只找会话', () => {
    expect(pollSource()).toContain('host.list()')
    expect(pollSource()).not.toContain('petRecords')
  })

  it('退订有释放，绑定与带气泡的会话不会被拆', () => {
    const source = runtimeSource()
    expect(source).toContain('host.release(channel.sessionId)')
    expect(source).toContain('bound.has(channel.sessionId)')
    expect(source).toContain('pending.has(channel.sessionId)')
    expect(source).toContain('FINISH_NOTICE_DEDUPE_MS')
  })

  it('发现失败保留上一轮订阅，不当成空列表', () => {
    expect(runtimeSource()).toContain("report('watch', error)")
  })

  it('后端广播 session/updated 时立刻对一次列表（合并 250ms）', () => {
    const source = runtimeSource()
    expect(source).toContain('scheduleDiscovery')
    expect(source).toContain('() => scheduleDiscovery()')
    const host = readFileSync(resolve(uiRoot, 'pet/agent/host.ts'), 'utf8')
    expect(host).toContain('onSessionUpdated')
    expect(host).toContain('onSessionUpdated: this.onSessionUpdated')
  })
})
