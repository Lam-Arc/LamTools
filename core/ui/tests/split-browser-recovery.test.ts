import { describe, expect, it } from 'vitest'
import { canRebuildLostTab, nativeTabLost } from '../src/split/browserRecovery'

// user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
// (判定只有两种来源算“标签丢了”：Rust 的 tab_not_found、前端映射缺失的原话；
//  别的失败必须继续如实显示，不能被误当成“重建一下就好”)。
describe('native tab loss detection', () => {
  it('treats Rust tab_not_found as a rebuild signal', () => {
    expect(nativeTabLost({ code: 'tab_not_found', message: '这个浏览器标签已经关闭', retriable: false })).toBe(true)
  })

  it('treats the local missing mapping as a rebuild signal', () => {
    expect(nativeTabLost(new Error('网页还没打开'))).toBe(true)
    expect(nativeTabLost('网页还没打开')).toBe(true)
  })

  it('keeps genuine failures visible instead of rebuilding', () => {
    expect(nativeTabLost({ code: 'tab_inactive', message: '这个标签现在在后台，切回来再试一次' })).toBe(false)
    expect(nativeTabLost({ code: 'internal', message: '浏览器内部出错了' })).toBe(false)
    expect(nativeTabLost({ code: 'certificate_error', message: '证书有问题' })).toBe(false)
    expect(nativeTabLost(undefined)).toBe(false)
    expect(nativeTabLost('')).toBe(false)
  })
})

// user:“同一个标签 2 秒内只重建一次，避免原生连续失败时空转”+
// (闸门是纯函数，边界写死在一处；组件只读结论)。
describe('lost tab rebuild throttle', () => {
  it('allows the first rebuild and blocks a second one inside the window', () => {
    expect(canRebuildLostTab(10_000, 0)).toBe(true)
    expect(canRebuildLostTab(10_500, 10_000)).toBe(false)
    expect(canRebuildLostTab(11_999, 10_000)).toBe(false)
    expect(canRebuildLostTab(12_000, 10_000)).toBe(true)
  })

  it('never blocks on a nonsensical clock or disabled window', () => {
    expect(canRebuildLostTab(Number.NaN, 10_000)).toBe(true)
    expect(canRebuildLostTab(10_000, Number.NaN)).toBe(true)
    expect(canRebuildLostTab(10_000, 10_000, 0)).toBe(true)
  })
})
