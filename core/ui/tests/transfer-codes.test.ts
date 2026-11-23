import { describe, expect, it } from 'vitest'

import {
  TRANSFER_CODES,
  isKnownTransferCode,
  transferErrorText,
  transferErrorTone,
} from '../src/transfer/codes'

/**
 * user:“文案与错误码一一对应（把 file_* 映射成中文人话）”+
 * 每一码都要有唯一一句人话；未知码不能吞掉传输层给的原文。
 */
describe('transfer error codes', () => {
  it('maps every code the engine can emit to one readable sentence', () => {
    const seen = new Map<string, string>()
    for (const code of TRANSFER_CODES) {
      expect(isKnownTransferCode(code), `${code} 应当有文案`).toBe(true)
      const text = transferErrorText(code)
      expect(text.trim().length, `${code} 的文案不能是空的`).toBeGreaterThan(0)
      // 一一对应：两个码不能落到同一句话上。
      expect(seen.has(text), `${code} 与 ${seen.get(text)} 撞了同一句文案`).toBe(false)
      seen.set(text, code)
      // 文案里不该出现原始码：给人看的是人话。
      expect(text).not.toContain('file_')
    }
  })

  it('keeps the engine message when the code is unknown', () => {
    const text = transferErrorText('file_something_new', 'peer closed the link')
    expect(text).toContain('peer closed the link')
    expect(isKnownTransferCode('file_something_new')).toBe(false)
  })

  it('falls back to a generic sentence when neither code nor message is known', () => {
    expect(transferErrorText('', '')).toBe('传输出错，稍后可以重试。')
    expect(transferErrorText('file_mystery', '')).toContain('传输出错')
  })

  it('treats a cancel as a normal ending, not a failure', () => {
    expect(transferErrorTone('file_cancelled')).toBe('info')
    expect(transferErrorTone('file_busy')).toBe('warn')
    expect(transferErrorTone('file_timeout')).toBe('warn')
    expect(transferErrorTone('file_disk_error')).toBe('error')
    expect(transferErrorTone('file_peer_error')).toBe('error')
  })
})
