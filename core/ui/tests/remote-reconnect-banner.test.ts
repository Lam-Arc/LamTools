/**
 * user:“短暂断线尽量无感（不弹提示），持续异常才轻量提示”“p2p_status 每次全量探测
 * Core → 加短 TTL 缓存”+
 * (P1 遗留 #5：验收脚本原先只断言 CLI 的 NOTICE，界面侧「短断线不弹横幅、长断线才弹」
 *  没有可断言的地方。这里把判定做成纯函数并单测，脚本再跑这一个文件即可。)
 */
import { describe, expect, it } from 'vitest'
import {
  NOTICE_AFTER_MS,
  outageBanner,
  shouldNotify,
  type LayeredStatus,
} from '@/app/remoteReconnect.ts'

const connected: LayeredStatus = { view: 'connected', reason: '-', connected: true }
const lost: LayeredStatus = { view: 'offline', connected: false }

describe('断线横幅', () => {
  it('连着的时候不弹', () => {
    expect(outageBanner({ elapsedMs: 60_000, status: connected }).visible).toBe(false)
  })

  it('短断线（20 秒以内）不弹', () => {
    expect(NOTICE_AFTER_MS).toBe(20_000)
    expect(shouldNotify(19_999)).toBe(false)
    expect(outageBanner({ elapsedMs: 3_000, status: lost }).visible).toBe(false)
    expect(outageBanner({ elapsedMs: 19_999, status: lost }).visible).toBe(false)
  })

  it('长断线才弹，并且给一句原因', () => {
    const banner = outageBanner({ elapsedMs: 20_000, status: lost })
    expect(banner.visible).toBe(true)
    expect(banner.text.length).toBeGreaterThan(0)
    expect(outageBanner({ elapsedMs: 120_000, status: lost }).visible).toBe(true)
  })

  it('降级也按同一套阈值：短的无感，长的说清为什么', () => {
    const degraded: LayeredStatus = { view: 'degraded', reason: 'core_unavailable', connected: true }
    expect(outageBanner({ elapsedMs: 5_000, status: degraded }).visible).toBe(false)
    const long = outageBanner({ elapsedMs: 30_000, status: degraded })
    expect(long.visible).toBe(true)
    expect(long.text).toContain('没有响应')
  })

  it('没有状态时说的是「断了，仍在重连」，不是一句空话', () => {
    const banner = outageBanner({ elapsedMs: 25_000, status: null })
    expect(banner.visible).toBe(true)
    expect(banner.text).toContain('重连')
  })
})
