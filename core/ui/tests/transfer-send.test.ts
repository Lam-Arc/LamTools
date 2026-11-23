import { describe, expect, it } from 'vitest'

import {
  MAX_TRANSFER_BYTES,
  mergeTransferTargets,
  sendEligibility,
  targetPathLabel,
  targetSubtitle,
  type TransferTarget,
} from '../src/transfer/send'

/**
 * user:“发送入口：列出已信任设备（含在线状态与直连/中继），选中后开始传输；对端离线/未配对
 * 给可读原因，不要静默失败”+
 * 每一种「点不动」都必须有一句话解释，不能让按钮静静躺在那儿。
 */
const online: TransferTarget = { id: 'd1', name: '手机', trusted: true, online: true, path: 'direct' }

describe('send eligibility', () => {
  it('allows a trusted, online device', () => {
    const result = sendEligibility(online, { path: 'C:/work/a.txt', size: 1024 })
    expect(result.allowed).toBe(true)
    expect(result.reason).toBe('')
    expect(result.warning).toBe('')
  })

  it('explains an unpaired device', () => {
    const result = sendEligibility({ ...online, trusted: false }, { path: 'C:/work/a.txt' })
    expect(result.allowed).toBe(false)
    expect(result.reason).toBe('这台设备还没配对，不能接收文件。')
  })

  it('explains an offline device', () => {
    const result = sendEligibility({ ...online, online: false }, { path: 'C:/work/a.txt' })
    expect(result.allowed).toBe(false)
    expect(result.reason).toBe('这台设备当前离线，等它连上再发。')
  })

  it('refuses files over the engine limit before dialing', () => {
    const result = sendEligibility(online, { path: 'C:/work/big.bin', size: MAX_TRANSFER_BYTES + 1 })
    expect(result.allowed).toBe(false)
    expect(result.reason).toContain('8 GiB')
    // 恰好等于上限仍然允许：上限是「不超过」。
    expect(sendEligibility(online, { path: 'C:/work/edge.bin', size: MAX_TRANSFER_BYTES }).allowed).toBe(true)
  })

  it('refuses paths that are not local', () => {
    expect(sendEligibility(online, { path: '' }).reason).toBe('没有选中文件。')
    expect(sendEligibility(online, { path: 'received/a.txt' }).allowed).toBe(false)
  })

  it('warns instead of blocking when the transfer will be slow', () => {
    const big = sendEligibility(online, { path: 'C:/work/big.bin', size: 2 * 1024 * 1024 * 1024 })
    expect(big.allowed).toBe(true)
    expect(big.warning).toContain('文件较大')
    const relay = sendEligibility({ ...online, path: 'relay' }, { path: 'C:/work/a.txt', size: 10 })
    expect(relay.allowed).toBe(true)
    expect(relay.warning).toContain('中继')
  })

  it('needs a device at all', () => {
    expect(sendEligibility(null, { path: 'C:/work/a.txt' }).reason).toBe('还没有可选设备。')
  })
})

describe('device list for the picker', () => {
  it('merges the trust list with the online roster: both sides count', () => {
    const targets = mergeTransferTargets(
      [{ id: 'd1', name: '手机' }, { id: 'd2', name: '平板' }],
      [{ id: 'd1', path: 'direct' }, { id: 'd3', name: '新设备', path: 'relay' }],
    )
    expect(targets.map((target) => target.id)).toEqual(['d1', 'd2', 'd3'])
    expect(targets[0]).toMatchObject({ trusted: true, online: true, path: 'direct' })
    expect(targets[1]).toMatchObject({ trusted: true, online: false })
    // 在线但还没落可信名单：照样列出来，但标记为不可发。
    expect(targets[2]).toMatchObject({ trusted: false, online: true, path: 'relay' })
  })

  it('drops entries without an id and defaults the channel to unknown', () => {
    const targets = mergeTransferTargets([{ name: '无 id' }], [{ id: 'd9' }])
    expect(targets).toHaveLength(1)
    expect(targets[0].path).toBe('unknown')
    expect(targetSubtitle(targets[0])).toContain('未配对')
  })

  it('says online/offline and the channel in words', () => {
    expect(targetSubtitle(online)).toBe('在线 · 直连')
    expect(targetSubtitle({ ...online, path: 'relay' })).toBe('在线 · 经中继')
    expect(targetSubtitle({ ...online, online: false })).toContain('离线')
    expect(targetPathLabel('direct')).toBe('直连')
  })
})
