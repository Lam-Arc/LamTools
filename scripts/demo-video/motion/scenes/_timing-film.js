/**
 * 成片（film.html）的节拍表：67.2s = 112 拍 = 28 小节 @ 100 BPM。
 *
 * 与 score.mjs 共用同一份时间：曲子不是贴在画面上的，两者读同一张表。
 * 每一个 cue 都落在 0.6s 的拍子上，切栏、成果落地、到点、收尾各有一记声音。
 */
;(function (root) {
  const BPM = 100
  const BEAT = 60 / BPM
  const BAR = BEAT * 4
  const TOTAL = 67.2
  const BARS = Math.round(TOTAL / BAR) // 28

  // 片子的三个关键点（与 film.html 的 BEATS 一致）
  const widenCode = 2.4
  const widenOffice = 17.4
  const widenGame = 36.0
  const endcard = 61.8

  const CHORDS = [
    { name: 'Am', at: 0, bars: 7, root: 110.0, tones: [220.0, 261.63, 329.63] },
    { name: 'F', at: 7, bars: 7, root: 87.31, tones: [174.61, 220.0, 261.63] },
    { name: 'C', at: 14, bars: 7, root: 130.81, tones: [196.0, 261.63, 329.63] },
    { name: 'G', at: 21, bars: 7, root: 98.0, tones: [196.0, 246.94, 293.66] },
  ]

  // 和弦音、上八度、声像
  const ARP = [440.0, 523.25, 659.25]
  const ARP_UP = [880.0, 1046.5, 1318.51]
  const PANS = [-0.35, 0.0, 0.35]
  const BUILD_MOTIF = [174.61, 220.0, 261.63, 349.23, 440.0]

  const api = {
    BPM,
    BEAT,
    BAR,
    TOTAL,
    BARS,
    CHORDS,
    ARP,
    ARP_UP,
    PANS,
    BUILD_MOTIF,

    // 重音：开场三块落入 / 代码拓宽 / 办公切入 / 游戏接管 / 收尾
    drop: [0.6, widenCode, widenOffice, widenGame, endcard],
    // 切栏的横扫
    shift: [widenCode, widenOffice, widenGame],
    // 单击、展开、读资料库、分屏、到点
    clickAt: widenGame,
    claimAt: widenCode,
    lineAt: 21.6,
    splitAt: 10.2,
    // 代码段：一行行写出来的五记落点
    build: { tiles: 6.0, ground: 7.8, body: 10.2, roof: 12.6, stem: 15.0, sweep: 14.4 },
    // 游戏段的三段并行与收束
    enter: [37.8, 39.0, 40.2],
    done: [47.4, 49.8, 52.2],
    reportAt: 57.6,
    withdrawAt: 60.0,
    // 钟表滴答：只在代码段那三拍半里响，走近 09:00
    tickFrom: 6.0,
    tickTo: 9.6,
    // 成果落地：一页一记轻响，画面里的列跟着推进一格
    arrive: [22.8, 24.6, 26.4, 28.2, 30.0, 31.8, 33.6, 35.4],
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = api
  root.FILM_TIMING = api
})(typeof globalThis !== 'undefined' ? globalThis : this)
