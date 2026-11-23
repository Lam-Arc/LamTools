import { describe, expect, it } from 'vitest'

import {
  explainStatus,
  isUsable,
  MAX_RECONNECT_ATTEMPTS,
  NOTICE_AFTER_MS,
  retryDelayMs,
  shouldNotify,
} from '../src/app/remoteReconnect.ts'

describe('remote reconnect policy', () => {
  // user:“自动恢复”+(先快后慢，有上限：1s、2s、4s、8s→5s 封顶)。
  it('backs off from one second and caps at five', () => {
    expect(retryDelayMs(1)).toBe(1_000)
    expect(retryDelayMs(2)).toBe(2_000)
    expect(retryDelayMs(3)).toBe(4_000)
    expect(retryDelayMs(4)).toBe(5_000)
    expect(retryDelayMs(10)).toBe(5_000)
    expect(retryDelayMs(0)).toBe(1_000)
  })

  // user:“短暂断线尽量无感（不弹提示），持续异常才轻量提示”+(20 秒是阈值)。
  it('stays silent for short outages and speaks up after the threshold', () => {
    expect(shouldNotify(3_000)).toBe(false)
    expect(shouldNotify(NOTICE_AFTER_MS - 1)).toBe(false)
    expect(shouldNotify(NOTICE_AFTER_MS)).toBe(true)
  })

  it('has a bounded retry budget', () => {
    expect(MAX_RECONNECT_ATTEMPTS).toBeGreaterThan(1)
    expect(MAX_RECONNECT_ATTEMPTS).toBeLessThanOrEqual(30)
  })

  // user:“只有业务真正可用才显示「已连接电脑」”+(隧道在但 Core 挂了不算可用)。
  it('treats a degraded tunnel as not usable', () => {
    expect(isUsable({ view: 'connected' })).toBe(true)
    expect(isUsable({ view: 'degraded', reason: 'core_unavailable' })).toBe(false)
    expect(isUsable({ view: 'connecting' })).toBe(false)
    expect(isUsable({ view: 'offline' })).toBe(false)
    expect(isUsable(null)).toBe(false)
  })

  // 老宿主只给 connected：仍然要尊重 connecting（正在拨号）。
  it('still understands the legacy connected flag', () => {
    expect(isUsable({ connected: true })).toBe(true)
    expect(isUsable({ connected: true, connecting: true })).toBe(false)
    expect(isUsable({ connected: false })).toBe(false)
  })

  // user:“界面文案要能解释为什么不是已连接”+(每种原因都要有一句话)。
  it('explains every reason in one short sentence', () => {
    expect(explainStatus({ view: 'degraded', reason: 'core_unavailable' })).toContain('没有响应')
    expect(explainStatus({ view: 'degraded', reason: 'device_rejected' })).toContain('没有被电脑接受')
    expect(explainStatus({ view: 'connecting' })).toContain('正在连接')
    expect(explainStatus({ view: 'offline' })).toContain('未开启')
    expect(explainStatus(null)).toContain('还没有连接')
  })
})
