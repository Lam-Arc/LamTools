/* Shared timing for the merged act.
 *
 * One table drives both the picture and the score: at 100 BPM a beat is 0.6s
 * and a bar is 2.4s, and every cue below sits on a whole number of beats. The
 * animation therefore lands on the music by construction rather than by ear.
 *
 * 16 bars — 38.4s — exactly.
 */
(function (root, factory) {
  const api = factory()
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.MERGED_TIMING = api
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const BPM = 100
  const BEAT = 60 / BPM
  const BAR = BEAT * 4

  const BEATS = [
    { id: 'A1', at: 0.0, dur: 3.6, note: '三块相连矩形，上下交错落入' },
    { id: 'A2', at: 3.6, dur: 3.0, note: '宽度依次重分配（1 → 2 → 3）' },
    { id: 'B1', at: 6.6, dur: 1.2, note: '光标点中第三块' },
    { id: 'B2', at: 7.8, dur: 1.8, note: '第三块接管整块表面' },
    { id: 'B3', at: 9.6, dur: 2.4, note: 'Agent 说出第一句话' },
    { id: 'C1', at: 12.0, dur: 1.2, note: '分为对话区 + 工作区' },
    { id: 'C2', at: 13.2, dur: 6.6, note: '右半边一点点搭出来' },
    { id: 'D1', at: 19.8, dur: 4.2, note: '点过程行 → 子代理矩形滑入接住气泡' },
    { id: 'D2', at: 24.0, dur: 3.6, note: '三块半透明矩形各自干活' },
    { id: 'D3', at: 27.6, dur: 3.0, note: '完成：闪一下 → 向上收起 → 回填过程行' },
    { id: 'E1', at: 30.6, dur: 2.4, note: '主代理：老板，搞完了，你看一下' },
    { id: 'E2', at: 33.0, dur: 2.4, note: '撤出，全屏让给成品' },
    { id: 'E3', at: 35.4, dur: 3.0, note: '成品定格' },
  ]
  const TOTAL = 38.4

  // ---- when things land ----
  const drop = [0.6, 1.8, 3.0] // each column finishes falling
  const shift = [3.6, 4.8, 6.0] // each column takes the width
  const clickAt = 7.2 // the cursor is on the third column
  const claimAt = BEATS[3].at // 7.8 it takes the whole surface
  const lineAt = BEATS[4].at // 9.6 the agent speaks
  const splitAt = BEATS[5].at // 12.0 chat + workspace
  const build = {
    tiles: 13.2,
    ground: 15.0,
    body: 16.2,
    roof: 16.8,
    stem: 18.0,
    crown: 18.3,
    sweep: 18.6,
  }
  const enter = [20.4, 22.2, 23.4] // sub-agent rectangles slide in (3 → 2 beats)
  const work = [21.6, 23.4, 24.6] // their progress draws begin
  const done = [28.2, 28.8, 29.4] // flash, one beat apart
  const row = [28.8, 29.4, 30.0] // the matching process row lands
  const reportAt = 31.2 // 老板，搞完了
  const withdrawAt = BEATS[11].at // 33.0

  // ---- the score ----
  const BARS = Math.round(TOTAL / BAR) // 16
  const CHORDS = [
    { at: 0, bars: 4, name: 'Am', root: 55.0, tones: [110.0, 220.0, 261.63, 329.63] },
    { at: 4, bars: 4, name: 'F', root: 43.65, tones: [87.31, 261.63, 349.23, 440.0] },
    { at: 8, bars: 4, name: 'G', root: 49.0, tones: [98.0, 246.94, 293.66, 392.0] },
    { at: 12, bars: 4, name: 'Am', root: 55.0, tones: [110.0, 220.0, 261.63, 329.63] },
  ]
  // the three sub-agents get a rising triad; their completion answers an octave up
  const ARP = [440.0, 523.25, 659.25] // A4 C5 E5
  const ARP_UP = [880.0, 1046.5, 1318.51] // A5 C6 E6
  const PANS = [-0.35, 0.0, 0.35]
  // the build rises through the F chord
  const BUILD_MOTIF = [174.61, 220.0, 261.63, 349.23, 440.0] // F3 A3 C4 F4 A4

  return {
    BPM,
    BEAT,
    BAR,
    BEATS,
    TOTAL,
    drop,
    shift,
    clickAt,
    claimAt,
    lineAt,
    splitAt,
    build,
    enter,
    work,
    done,
    row,
    reportAt,
    withdrawAt,
    BARS,
    CHORDS,
    ARP,
    ARP_UP,
    PANS,
    BUILD_MOTIF,
  }
})
