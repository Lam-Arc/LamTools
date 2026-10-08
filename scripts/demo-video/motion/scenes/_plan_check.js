const { seg, lerp, ease, style, stagger } = window.MotionKit

/* ---------------------------------------------------------------------------
 * 三段式整体排布：小游戏 → 代码 → 办公，一条连续的片子。
 *
 *   三栏从头到尾都在台上，谁聚焦谁变宽。
 *   小游戏（最长，奇观）→ 代码（定时与时间流逝住在右边两条窄栏里，
 *   滴答到点自己动）→ 办公（左虚化代码 + 资料库卡片，中聊天，右成果）。
 *
 * 100 BPM：一拍 0.6s。64.8s = 108 拍 = 27 小节。
 * ------------------------------------------------------------------------ */

const PANEL = { w: 1680, h: 888 }
const EQ = 560
const CHAT_W = 440

const BEATS = [
  { id: 'O1', at: 0.0, dur: 1.8, note: '三块等宽交错落入' },
  { id: 'O2', at: 2.2, dur: 2.2, note: '宽度给第一块：代码拓宽聚焦——直接进代码段，不点第二遍' },
  { id: 'C1', at: 4.0, dur: 1.8, note: '右侧两条窄栏虚化：定时卡片 + 时间流逝' },
  { id: 'C2', at: 5.8, dur: 2.0, note: '代码稳定推进' },
  { id: 'C3', at: 7.8, dur: 1.8, note: '时间在走：09:00 逼近"现在"' },
  { id: 'C4', at: 9.6, dur: 0.6, note: '滴答——到点了' },
  { id: 'C5', at: 10.2, dur: 2.4, note: '代码上下分屏：新任务开始' },
  { id: 'C6', at: 12.6, dur: 1.8, note: '那个任务跑（干脆）' },
  { id: 'C7', at: 14.4, dur: 1.2, note: '做完，分屏收起' },
  { id: 'C8', at: 15.6, dur: 1.8, note: '隐去辅助内容，回到三栏（聚焦仍是代码）' },
  { id: 'D1', at: 17.4, dur: 3.0, note: '点第二块：左虚化代码+资料库卡片，中聊天，右成果' },
  { id: 'D2', at: 20.4, dur: 1.2, note: '你说一句话' },
  { id: 'D3', at: 21.6, dur: 1.2, note: 'Agent：用户想要 xxx，我看看资料库' },
  { id: 'D4', at: 22.8, dur: 1.8, note: '从左侧资料库提取 → 过程行①' },
  { id: 'D5', at: 24.6, dur: 1.8, note: '写入内容 → 过程行②' },
  { id: 'D6', at: 26.4, dur: 1.8, note: '把过程行扔到右边的成果区' },
  { id: 'D7', at: 28.2, dur: 2.4, note: '变成实际渲染出来的文件' },
  { id: 'D8', at: 30.6, dur: 1.8, note: '定格' },
  { id: 'E1', at: 32.4, dur: 1.8, note: '点第三块：游戏接管整块表面，另外两块退场' },
  { id: 'E2', at: 34.2, dur: 2.4, note: 'Agent 说第一句话' },
  { id: 'E3', at: 36.6, dur: 7.2, note: '作品一点点长出来' },
  { id: 'E4', at: 43.8, dur: 7.2, note: '子代理三段：递增加速' },
  { id: 'E5', at: 51.0, dur: 3.0, note: '闪一下、收起、过程行回填' },
  { id: 'E6', at: 54.0, dur: 2.4, note: '汇报：老板，搞完了' },
  { id: 'E7', at: 56.4, dur: 1.8, note: '成品定格：全屏让给成品' },
  { id: 'F1', at: 58.2, dur: 4.2, note: '暗场，名字落定' },
]
const TOTAL = 62.4
const at = (id) => BEATS.find((b) => b.id === id).at

const COLS = [
  { title: '实现功能', sub: '一句话到能用的应用', keeps: '作品' },
  { title: '办公', sub: '报表 · 文档 · 演示', keeps: '资料库' },
  { title: '做小游戏', sub: '能玩的那种', keeps: '作品' },
]
const DOCS = ['上周周报', '上上周周报', '季度汇总']
const LIB_DOCS = ['上周的周报', '汇报模板', '数据口径']
const ROWS = [
    { at: 34.4, top: 40,  kind: 'bubble', text: '好，现在我来实现这个经营建造游戏。' },
    { at: 44.7, top: 120, kind: 'prow', text: '帮我把初始村落搭起来' },
    { at: 46.5, top: 172, kind: 'prow', text: '你负责地面和道路' },
    { at: 47.7, top: 224, kind: 'prow', text: '做一下资源条和建造菜单' },
    { at: 51.9, top: 296, kind: 'prow', text: '村落搭好了' },
    { at: 52.5, top: 348, kind: 'prow', text: '道路铺完了' },
    { at: 53.1, top: 400, kind: 'prow', text: '资源条和菜单好了' },
    { at: 54.2, top: 470, kind: 'bubble', text: '老板，搞完了，你看一下。' },
    { at: 20.6, top: 40,  kind: 'bubble', text: '把上周的数据整理成一份周报，按上次的格式' },
    { at: 21.8, top: 124, kind: 'prow', text: '用户想要周报，我看看资料库有没有有效信息' },
    { at: 23.0, top: 180, kind: 'prow', text: '从资料库提取：上周的格式与口径' },
    { at: 24.8, top: 236, kind: 'prow', text: '写入这周的数据' },
    { at: 26.6, top: 292, kind: 'prow', text: '生成文件，放进成果区' },
  ]

const ENTER = [44.4, 46.2, 47.4]
const DONE = [51.3, 51.9, 52.5]
const MINI = [[0, 150, 1], [1, 110, 0], [1, 170, 2], [2, 90, 0], [0, 190, 1], [1, 140, 0], [2, 100, 2], [0, 160, 1], [1, 120, 0], [2, 150, 2]]
const CODE_LINES = [[0, 300, 1], [1, 240, 0], [2, 380, 2], [1, 200, 1], [3, 340, 0], [2, 260, 2], [0, 420, 1], [1, 180, 0], [2, 300, 2], [4, 220, 1], [1, 360, 0], [2, 240, 2]]
const TONE = ['rgba(255,255,255,0.07)', 'rgba(255,255,255,0.13)', 'rgba(255,255,255,0.24)']
const TONE_ADD = ['rgba(120,200,150,0.18)', 'rgba(120,200,150,0.28)', 'rgba(120,200,150,0.4)']

const els = {}
const $ = (id) => (els[id] = els[id] || document.getElementById(id))
window.sceneMeta = { duration: TOTAL, width: 1920, height: 1080 }

/* ------------------------------------------------------------ static DOM */
function buildDom() {
  let cols = ''
  COLS.forEach((col, i) => {
    cols += `<div class="col" id="col${i}" style="z-index:${i === 2 ? 3 : 1}">
      <div class="col-surface" id="surf${i}"></div>
      <div class="col-title" id="title${i}">${col.title}</div>
      <div class="col-sub" id="colSub${i}">${col.sub}</div>
      <div class="mini-head" id="mini${i}" style="opacity:0">${col.keeps}</div>
      <div id="keep${i}"></div>
      <div id="aux${i}" style="position:absolute;inset:0"></div>
    </div>`
  })
  cols += `<div class="divider" id="div0"></div><div class="divider" id="div1"></div>`
  $('colLayer').innerHTML = cols

  // 代码段的辅助栏内容（挂在 col1 / col2 上，代码聚焦时才显示）
  // 代码段的右两条窄栏：一条是实时小编辑器（看得见代码出来），
  // 另一条上下叠着定时卡片与时间环——两样都不占地方，紧凑一些
 [1, 110, 0], [1, 170, 2], [2, 90, 0], [0, 190, 1], [1, 140, 0], [2, 100, 2], [0, 160, 1], [1, 120, 0], [2, 150, 2]]
  $('aux1').innerHTML = `<div class="aux-head" id="auxHead1" style="position:absolute;left:14px;top:22px;font-size:15px;letter-spacing:0.06em;color:rgba(238,240,244,0.55);opacity:0">run.ts · 实时</div>
    <div id="miniEd" style="position:absolute;inset:0;opacity:0">
      ${MINI.map(([ind, w, tone], i) => `<div class="cline" data-mline="${i}" style="left:${14 + ind * 13}px;top:${58 + i * 24}px;width:${w}px;background:${tone === 'a' ? 'rgba(120,200,150,0.4)' : TONE[tone]};opacity:0"></div>`).join('')}
    </div>`
  $('aux2').innerHTML = `<div class="aux-head" id="auxHead2" style="position:absolute;left:16px;top:22px;font-size:15px;letter-spacing:0.06em;color:rgba(238,240,244,0.55);opacity:0">定时</div>
    <div class="job" id="job" style="left:16px;right:14px;top:52px;padding:12px 12px 12px;opacity:0">
      <div class="job-title" style="font-size:17px">看一遍代码改动</div>
      <div class="job-when" style="margin-top:6px;font-size:15px">每天 09:00</div>
      <div class="job-sub" id="jobSub" style="margin-top:8px;font-size:14px">上次 09:00 · 无阻塞</div>
      <div class="job-dot" style="right:12px;top:16px"></div>
      <div class="job-flash" id="jobFlash"></div></div>
    <div id="ringWrap" style="position:absolute;left:0;right:0;top:260px;height:200px;opacity:0">
      <svg width="140" height="140" viewBox="0 0 140 140" style="position:absolute;left:50%;top:10px;margin-left:-70px">
        <circle cx="70" cy="70" r="62" fill="none" stroke="rgba(255,255,255,0.07)" stroke-width="8"/>
        <circle id="ringFill" cx="70" cy="70" r="62" fill="none" stroke="rgba(150,135,245,0.95)" stroke-width="8"
          stroke-linecap="round" stroke-dasharray="389.6" stroke-dashoffset="389.6" transform="rotate(-90 70 70)"/>
      </svg>
      <div id="ringCenter" style="top:52px"><div id="ringTime" style="font-size:24px">09:00</div><div id="ringCap" style="font-size:13px">下次运行</div></div>
    </div>`

  // 办公段的资料库卡片（压在 col0 上，办公聚焦时才显示）
  let lib = `<div class="lib-card"><div class="lib-title">资料库</div></div>`
  LIB_DOCS.forEach((name, k) => {
    lib += `<div class="lib-doc" id="libDoc${k}" style="top:${104 + k * 44}px;opacity:0">
      <div class="doc-sq"></div><div class="doc-line" style="width:${100 - k * 18}px"></div>
      <div class="doc-hi" id="libHi${k}"></div></div>`
  })
  $('aux0').insertAdjacentHTML('beforeend', `<div id="libLayer" style="position:absolute;inset:0;opacity:0">${lib}</div>`)

  // 成果区（col2 内，办公聚焦时才显示）
  let page = `<div class="page" id="page" style="left:40px;top:96px;width:600px;height:600px;opacity:0">
    <div class="page-line" style="left:32px;top:36px;width:220px;height:16px;background:rgba(255,255,255,0.24)"></div>`
  for (let i = 0; i < 6; i += 1) {
    page += `<div class="page-line" data-pline="${i}" style="left:32px;top:${90 + i * 34}px;width:${420 - (i % 3) * 60}px;opacity:0"></div>`
  }
  for (let b = 0; b < 5; b += 1) {
    const h = 60 + ((b * 67) % 110)
    page += `<div class="page-bar" data-pbar="${b}" style="left:${44 + b * 96}px;top:${560 - h}px;width:60px;height:${h}px;opacity:0"></div>`
  }
  page += `</div>`
  $('aux2').insertAdjacentHTML('beforeend', `<div id="resultLayer" style="position:absolute;inset:0;opacity:0">${page}</div>`)

  // 聊天层（跟着聚焦栏走）
  let chat = ''

  ROWS.forEach((row, i) => {
    chat += row.kind === 'bubble'
      ? `<div class="bubble me" data-row="${i}" style="left:24px;top:${row.top}px;width:360px;height:52px;opacity:0"><div class="bubble-text">${row.text}</div></div>`
      : `<div class="prow" data-row="${i}" style="top:${row.top}px;opacity:0"><div class="prow-dot"></div><div class="prow-text">${row.text}</div></div>`
  })
  $('stageLayer').innerHTML = `<div id="chatLayer" style="position:absolute;top:0;height:888px;overflow:hidden">${chat}</div>
    <div id="workLayer" style="position:absolute;top:0;height:888px;overflow:hidden">
      <div id="tiles"></div><div id="subs"></div></div>`

  let tiles = ''
  const G = { cols: 4, rows: 3, size: 96, gap: 16 }
  for (let r = 0; r < G.rows; r += 1) {
    for (let c = 0; c < G.cols; c += 1) {
      tiles += `<div class="tile" data-tile="${r * G.cols + c}" style="left:${300 + c * (G.size + G.gap)}px;top:${110 + r * (G.size + G.gap)}px;width:${G.size}px;height:${G.size}px;opacity:0"></div>`
    }
  }
  let subs = ''
  for (let i = 0; i < 3; i += 1) {
    let inner = `<div class="sub-flash" id="subRflash${i}"></div>
      <div style="position:absolute;left:18px;top:20px;width:${90 + i * 20}px;height:10px;border-radius:5px;background:rgba(255,255,255,0.22)"></div>
      <div style="position:absolute;left:18px;top:44px;width:9px;height:9px;border-radius:50%;background:rgba(101,84,217,0.9)"></div>`
    for (let k = 0; k < 5; k += 1) {
      inner += `<div style="position:absolute;left:18px;top:${76 + k * 34}px;width:${120 + ((k * 37 + i * 19) % 90)}px;height:9px;border-radius:4px;background:rgba(255,255,255,0.13)"></div>`
    }
    subs += `<div class="sub" id="subR${i}" style="opacity:0">${inner}</div>`
  }
  $('tiles').innerHTML = tiles
  $('subs').innerHTML = subs

  let code = `<div class="band-tag" id="codeTag" style="opacity:0">core / scheduler / run.ts</div>`
  CODE_LINES.forEach(([indent, w, tone], i) => {
    code += `<div class="cline" data-cline="${i}" style="left:${58 + indent * 26}px;top:${70 + i * 28}px;width:${w}px;background:${TONE[tone]};opacity:0"></div>`
    code += `<div class="cline-num" data-cnum="${i}" style="top:${73 + i * 28}px;opacity:0">${i + 1}</div>`
  })
  code += `<div id="caret" style="position:absolute;width:2px;height:18px;border-radius:1px;background:rgba(150,135,245,0.9);opacity:0"></div>`
  code += `<div class="cline add" id="traceLine" style="left:${58 + 2 * 26}px;top:${70 + 12 * 28}px;width:190px;opacity:0"></div>`
  const BOT = [[0, 260, 1], [1, 200, 0], [1, 320, 2], [2, 180, 0], [0, 300, 1]]
  BOT.forEach(([indent, w, tone], i) => {
    code += `<div class="cline add" data-bline="${i}" style="left:${58 + indent * 26}px;top:${70 + i * 28}px;width:${w}px;background:${TONE_ADD[tone]};opacity:0"></div>`
    code += `<div class="cline-num" data-bnum="${i}" style="top:${73 + i * 28}px;opacity:0">${13 + i}</div>`
  })
  code += `<div class="band-hair" id="bandHair"></div><div class="band-tag" id="botTag" style="opacity:0">09:00 · 例行检查</div>`
  $('col0').insertAdjacentHTML('beforeend', `<div id="codeLayer" style="position:absolute;inset:0;opacity:0">${code}</div>`)

  let track = ''
  for (const b of BEATS) {
    track += `<div class="track-block" data-block="${b.id}" style="left:${((b.at / TOTAL) * 100).toFixed(2)}%;width:${((b.dur / TOTAL) * 100).toFixed(2)}%"></div>`
    track += `<div class="track-name" style="left:${((b.at / TOTAL) * 100).toFixed(2)}%">${b.id}</div>`
  }
  $('trackBlocks').innerHTML = track
}
buildDom()

/* ------------------------------------------------------------------ render */
// 几何：三栏位置固定，只有宽度变
const KEYS = [
  { at: at('O2'), dur: 2.2, w: [1120, 280, 280], o: 0, fo: -1, from: [560, 560, 560] },
  { at: at('D1'), dur: 3.0, w: [400, 600, 680], o: 1, fo: 0, from: [1120, 280, 280] },
  { at: at('E1'), dur: 1.8, w: [0, 0, 1680], o: 2, fo: 1, from: [400, 600, 680] },
]

function geometry(t) {
  if (t < at('O2')) {
    const step = t < at('O2') ? -1 : t < at('O2') + 1.0 ? 0 : t < at('O2') + 2.0 ? 1 : 2
    const blend = step < 0 ? 1 : ease.expoOut(seg(t, at('O2') + step * 1.0, at('O2') + step * 1.0 + 0.6))
    const target = step < 0 ? [EQ, EQ, EQ] : [340, 340, 1000].map((w, i) => (i === step ? 1000 : w))
    return { w: [EQ, EQ, EQ].map((v, i) => lerp(v, target[i], blend)), o: step, p: blend, fo: -1, grab: 0, give: 0 }
  }
  let key = KEYS[1]
  let u = 0
  for (const k of KEYS) {
    if (t >= k.at) { key = k; u = seg(t, k.at, k.at + k.dur) }
  }
  // 聚焦的那块先动（向右展开），远端那块先让位，中间那块被夹着走——
  // 三块之和恒等于台面宽，所以是一个方向性的推挤波，不是三块同时缩放
  const e = ease.cubicInOut(u)
  const others = [0, 1, 2].filter((i) => i !== key.o)
  const far = others[1]
  const w = [0, 0, 0]
  w[key.o] = lerp(key.from[key.o], key.w[key.o], e)
  w[far] = lerp(key.from[far], key.w[far], Math.min(1, u * 1.3))
  w[others[0]] = PANEL.w - w[key.o] - w[far]
  return { w, o: key.o, p: e, fo: key.fo, grab: 1, give: 1 }
}

window.renderFrame = (t) => {
  let fly = ''
  const { w, o, p: transP, fo: fromOwner } = geometry(t)
  const claim = ease.cubicInOut(seg(t, at('E1'), at('E1') + 1.8))
  const give = claim
  const titleFade = 1 - ease.quintOut(seg(t, at('O2') + 0.6, at('O2') + 2.2))
  const codeIn = seg(t, at('O2') + 0.5, at('O2') + 1.9)
  const codeOut = seg(t, at('C8'), at('C8') + 0.9)
  const officeIn = seg(t, at('D1') + 0.3, at('D1') + 2.2)
  const officeA = officeIn * (1 - seg(t, at('E1'), at('E1') + 1.0))
  const auxHold = seg(t, at('C1') + 1.4, at('C1') + 2.6) * (1 - seg(t, at('C8'), at('C8') + 0.9))

  // O1：三块交错落入——开场唯一的一次入场
  COLS.forEach((_, i) => {
    const arrive = ease.softBack(stagger(t, i, { start: 0.0, each: 0.5, dur: 0.5 }))
    const travel = (1 - arrive) * (i % 2 === 0 ? -(PANEL.h + 40) : PANEL.h + 40)
    style($(`col${i}`), { transform: `translateY(${travel.toFixed(1)}px)` })
  })

  // 三栏
  const xs = [0]
  COLS.forEach((_, i) => {
    const x = i === 0 ? 0 : xs[i] // placeholder, recomputed below
  })
  let acc = 0
  const lefts = []
  COLS.forEach((_, i) => { lefts.push(acc); acc += Math.max(0, w[i]) })
  COLS.forEach((_, i) => {
    style($(`col${i}`), { left: `${lefts[i].toFixed(1)}px`, width: `${Math.max(0, w[i]).toFixed(1)}px` })
    const dim = i === o ? 1 : lerp(1, 0.5, give)
    const focus = i === o ? transP : i === fromOwner ? 1 - transP : 0
    style($(`surf${i}`), { opacity: 0.85 * focus * (1 - claim * 0.9) })
    style($(`title${i}`), { opacity: dim * (1 - give) * titleFade })
    style($(`colSub${i}`), { opacity: dim * 0.9 * (1 - give) * titleFade })
    
  })
  style($('div0'), { left: `${lefts[1].toFixed(1)}px`, opacity: (w[0] > 4 && w[1] > 4 ? 1 : 0) * seg(t, 0.9, 1.8) })
  style($('div1'), { left: `${lefts[2].toFixed(1)}px`, opacity: (w[1] > 4 && w[2] > 4 ? 1 : 0) * seg(t, 0.9, 1.8) })

  const codeOn = codeIn * (1 - codeOut) > 0.02
  const officeOn = officeA > 0.02
  const colX = (i) => lefts[i]
  const colW = (i) => Math.max(0, w[i])

  const codeA = codeIn * (1 - codeOut)
  // 隐去辅助内容之后代码留在台上，直到办公段把它接过去虚化
  const codeHold = Math.max(codeA, seg(t, at('C8'), at('D1') + 1.2) * (1 - officeA))
  const codeVis = Math.max(codeHold, officeA * 0.5)
  // 主区是 Sunday 的工作台：聊天 + 代码编辑器；办公段它退成左边的虚化背景
  style($('codeLayer'), {
    left: `${lerp(417, 0, officeA).toFixed(1)}px`,
    width: `${lerp(Math.max(0, colW(0) - 441), colW(0), officeA).toFixed(1)}px`,
    opacity: codeVis,
  })
  const vis = codeVis
  /* ---- 聊天层：游戏段挂在 col2，办公段挂在 col1 ---- */
  const gameChat = (o === 2 ? 1 : 0) * (1 - seg(t, at('E7'), at('E7') + 0.8))
  const codeChat = codeA
  const chatA = o === 2 ? gameChat : o === 1 ? officeA : codeChat
  style($('chatLayer'), {
    left: o === 1 ? `${(colX(1) + 24).toFixed(1)}px` : '24px',
    width: `${(o === 1 ? Math.max(0, colW(1) - 48) : o === 0 ? 392 : 616).toFixed(1)}px`,
    opacity: chatA,
  })
  const withdraw = ease.cubicInOut(seg(t, at('E7'), at('E7') + 1.4))
  style($('workLayer'), {
    left: `${lerp(colX(2) + 641, 0, withdraw).toFixed(1)}px`,
    width: `${lerp(Math.max(0, colW(2) - 641), PANEL.w, withdraw).toFixed(1)}px`,
    opacity: (o === 2 ? seg(t, at('E1') + 0.5, at('E1') + 1.4) : 0),
  })
  style($('tiles'), { transform: `translateX(${((PANEL.w - 1039) / 2 * withdraw).toFixed(1)}px)` })

  // 气泡与过程行
  ROWS.forEach((row, i) => {
    const node = document.querySelector(`[data-row="${i}"]`)
    if (!node) return
    const p = ease.quintOut(seg(t, row.at, row.at + 0.5))
    const visible = i <= 7 ? gameChat : i <= 12 ? officeA : codeChat
    style(node, { opacity: p * 0.95 * visible })
  })

  /* ---- 游戏段：网格 + 三块子代理 ---- */
  document.querySelectorAll('[data-tile]').forEach((node) => {
    const p = stagger(t, Number(node.dataset.tile), { start: at('E2') + 1.0, each: 0.12, dur: 0.5 })
    style(node, { opacity: Math.min(1, p * 2.2) * (o === 2 ? 1 : 0) })
  })
  const workW = Math.max(0, colW(2) - 641)
  const sw = (workW - 2) / 3
  for (let i = 0; i < 3; i += 1) {
    const slide = ease.expoOut(seg(t, ENTER[i], ENTER[i] + 0.62))
    const leave = ease.quintOut(seg(t, DONE[i] + 0.45, DONE[i] + 1.2))
    style($(`subR${i}`), {
      left: `${(i * (sw + 1)).toFixed(1)}px`, width: `${sw.toFixed(1)}px`,
      opacity: Math.min(1, seg(t, ENTER[i], ENTER[i] + 0.2) * 1.6) * (1 - leave) * (o === 2 ? 1 : 0),
      transform: `translateY(${((1 - slide) * -900 + leave * -900).toFixed(1)}px)`,
    })
    style($(`subRflash${i}`), { opacity: (Math.sin(Math.PI * seg(t, DONE[i], DONE[i] + 0.42)) * 0.16 * (o === 2 ? 1 : 0)).toFixed(3) })
  }

  /* ---- 代码段：代码在左，定时与时间在右两条窄栏；办公段它退成虚化的背景 ---- */


  // 代码稳定推进：行按拍落，光标跟着最后一行走
  let caretIdx = 0
  CODE_LINES.forEach(([indent, w], i) => {
    const p = ease.expoOut(seg(t, at('C2') + i * 0.1, at('C2') + i * 0.1 + 0.45))
    style(document.querySelector(`[data-cline="${i}"]`), { opacity: Math.min(1, p * 1.4) * vis, transform: `scaleX(${p.toFixed(4)})` })
    style(document.querySelector(`[data-cnum="${i}"]`), { opacity: Math.min(1, p * 1.2) * vis * 0.9 })
    if (t >= at('C2') + i * 0.1) caretIdx = i
  })
  {
    const [indent, w] = CODE_LINES[caretIdx]
    const p = ease.expoOut(seg(t, at('C2') + caretIdx * 0.1, at('C2') + caretIdx * 0.1 + 0.45))
    const on = codeA > 0.4 && t < at('C4') + 0.2
    style($('caret'), {
      left: `${(58 + indent * 26 + w * p + 8).toFixed(1)}px`,
      top: `${(72 + caretIdx * 28).toFixed(1)}px`,
      opacity: on ? vis : 0,
    })
  }
  // 例行检查做完之后，代码里多出一行改动——它来过的痕迹
  {
    const p = ease.quintOut(seg(t, at('C7') + 0.4, at('C7') + 1.0)) * Math.max(codeHold, officeA * 0.5)
    style($('traceLine'), { opacity: p, transform: `scaleX(${ease.expoOut(p).toFixed(4)})` })
  }

  const auxA = codeA
  // 小编辑器：Agent 跑的时候，代码在这里一行行出来
  style($('miniEd'), { opacity: auxA })
  MINI.forEach(([ind, w], i) => {
    const p = ease.expoOut(seg(t, at('C2') + 0.6 + i * 0.5, at('C2') + 0.6 + i * 0.5 + 0.5))
    style(document.querySelector(`[data-mline="${i}"]`), { opacity: Math.min(1, p * 1.4) * auxA, transform: `scaleX(${p.toFixed(4)})` })
  })
  style($('job'), { opacity: auxA, transform: `translateY(${((1 - seg(t, at('O2') + 0.7, at('O2') + 2.0)) * 14).toFixed(1)}px)` })
  style($('auxHead1'), { opacity: auxA })
  style($('auxHead2'), { opacity: auxA })

  // 时间流动：环从“上次运行”往“下次 09:00”走，走满即到点
  const fill = seg(t, at('C2') + 0.4, at('C4'))
  const deg = 360 * ease.sineInOut(fill)
  const CIRC = 2 * Math.PI * 62
  style($('ringFill'), { strokeDashoffset: `${(CIRC * (1 - ease.sineInOut(fill))).toFixed(1)}` })
  style($('ringWrap'), {
    opacity: auxA,
    transform: `scale(${(1 + Math.sin(Math.PI * seg(t, at('C4'), at('C4') + 0.6)) * 0.045).toFixed(3)})`,
  })
  const tickP = Math.sin(Math.PI * seg(t, at('C4') - 0.1, at('C4') + 0.5)) * auxA
  style($('jobFlash'), { opacity: (tickP * 0.2).toFixed(3) })
  // 到点：一圈从环心荡开，卡片的状态行换成“刚刚”
  const ringP = seg(t, at('C4'), at('C4') + 0.7)
  if (ringP > 0 && ringP < 1 && auxA > 0.3) {
    const r = lerp(52, 104, ease.expoOut(ringP))
    fly += `<div style="position:absolute;left:${(colX(2) + 140 - r).toFixed(1)}px;top:${(360 - r).toFixed(1)}px;width:${r * 2}px;height:${r * 2}px;border-radius:50%;border:1.5px solid rgba(150,135,245,${(Math.sin(Math.PI * ringP) * 0.7).toFixed(3)})"></div>`
  }
  const jobSubText = t > at('C4') + 0.35 ? '刚刚 · 运行完成' : '上次 09:00 · 无阻塞'
  if ($('jobSub').textContent !== jobSubText) $('jobSub').textContent = jobSubText
  style($('jobSub'), { color: t > at('C4') + 0.35 ? 'rgba(190,180,250,0.9)' : 'rgba(238,240,244,0.45)' })

  // 上下分屏：缝从左往右画出来，下半屏的新任务干脆跑完
  const open = ease.cubicInOut(seg(t, at('C5'), at('C5') + 1.2))
  const close = ease.cubicInOut(seg(t, at('C7'), at('C7') + 1.2))
  const split = open * (1 - close) * codeA
  const bandTop = lerp(0, 444, split)
  style($('codeTag'), { opacity: (1 - split * 0.5) * vis })
  style($('botTag'), { top: `${(bandTop + 22).toFixed(1)}px`, opacity: split })
  style($('bandHair'), { top: `${(bandTop + 96).toFixed(1)}px`, opacity: split > 0.02 ? split : 0, transform: `scaleX(${Math.min(1, split * 1.6).toFixed(4)})`, transformOrigin: '0 50%' })
  document.querySelectorAll('[data-bline]').forEach((node) => {
    const i = Number(node.dataset.bline)
    const p = ease.expoOut(stagger(t, i, { start: at('C5') + 0.9 + i * 0.22, each: 0.24, dur: 0.4 }))
    style(node, { top: `${(bandTop + 64 + i * 28).toFixed(1)}px`, opacity: Math.min(1, p * 1.5) * split, transform: `scaleX(${p.toFixed(4)})` })
    const num = document.querySelector(`[data-bnum="${i}"]`)
    if (num) style(num, { top: `${(bandTop + 67 + i * 28).toFixed(1)}px`, opacity: Math.min(1, p * 1.2) * split * 0.9 })
  })

  /* ---- 办公段：左虚化代码 + 资料库卡片，中聊天，右成果 ---- */
  style($('libLayer'), { opacity: officeA })
  document.querySelectorAll('[id^="libDoc"]').forEach((node) => {
    style(node, { opacity: officeA })
  })
  style($('resultLayer'), { opacity: officeA })
  const readP = Math.sin(Math.PI * seg(t, at('D4'), at('D4') + 1.2)) * officeA
  style($('libHi0'), { opacity: readP.toFixed(3) })
  if (readP > 0.05) {
    fly += `<div class="doc" style="left:${(colX(0) + 30 + (1 - ease.cubicInOut(readP)) * 40).toFixed(1)}px;top:${(104 - readP * 10).toFixed(1)}px;width:${lerp(140, 110, readP).toFixed(1)}px;height:34px;opacity:${(officeA * Math.sin(Math.PI * readP) * 0.9).toFixed(3)}"></div>`
  }
  const pageP = ease.quintOut(seg(t, at('D7'), at('D7') + 1.4)) * officeA
  style($('page'), { opacity: pageP, transform: `translateY(${((1 - pageP) * 24).toFixed(1)}px)` })
  document.querySelectorAll('[data-pline]').forEach((node) => {
    const i = Number(node.dataset.pline)
    const p = stagger(t, i, { start: at('D7') + 0.5, each: 0.14, dur: 0.4 })
    style(node, { opacity: Math.min(1, p * 2) * pageP, transform: `scaleX(${ease.expoOut(p).toFixed(4)})` })
  })
  document.querySelectorAll('[data-pbar]').forEach((node) => {
    const i = Number(node.dataset.pbar)
    const p = stagger(t, i, { start: at('D7') + 1.1, each: 0.16, dur: 0.5 })
    style(node, { opacity: Math.min(1, p * 1.8) * pageP, transform: `scaleY(${ease.quintOut(p).toFixed(4)})` })
  })

  /* ---- 光标：三段都由“点中它所在的那一块”进场，同一个动作 ---- */
  const clickShot = (when, from, to) => {
    if (t < when - 1.0 || t > when + 1.0) return ''
    const travel = ease.sineInOut(seg(t, when - 0.8, when + 0.1))
    const press = Math.sin(Math.PI * seg(t, when + 0.1, when + 0.45))
    const alpha = seg(t, when - 1.0, when - 0.7) * (1 - seg(t, when + 0.6, when + 1.0))
    let out = `<div class="cursor" style="left:${lerp(from.x, to.x, travel).toFixed(1)}px;top:${lerp(from.y, to.y, travel).toFixed(1)}px;opacity:${alpha.toFixed(3)};transform:scale(${(1 - press * 0.3).toFixed(3)})"></div>`
    const rp = seg(t, when + 0.15, when + 1.0)
    if (rp > 0 && rp < 1) {
      out += `<div class="ripple" style="left:${to.x - 40}px;top:${to.y - 40}px;width:80px;height:80px;opacity:${(Math.sin(Math.PI * rp) * 0.9).toFixed(3)};transform:scale(${lerp(0.3, 3.2, ease.expoOut(rp)).toFixed(3)})"></div>`
    }
    return out
  }
  fly += clickShot(at('D1'), { x: lefts[0] + 620, y: 690 }, { x: lefts[1] + 140, y: 430 })
  fly += clickShot(at('E1'), { x: lefts[1] + 420, y: 430 }, { x: lefts[2] + 340, y: 430 })

  /* ---- 收尾 ---- */
  const dark = ease.sineInOut(seg(t, at('F1') + 0.6, at('F1') + 1.8))
  style($('endcard'), { opacity: dark })
  style($('colLayer'), { opacity: 1 - dark * 0.9 })
  style($('stageLayer'), { opacity: 1 - dark })

  /* ---- 字幕 + 时间轴 ---- */
  let current = BEATS[0]
  for (const b of BEATS) if (t >= b.at) current = b
  $('capTitle').textContent = `${current.id} · ${current.note}`
  $('capHint').textContent = t < at('C1')
    ? '开场把"聚焦=变宽"教给观众；小游戏拿最长的篇幅'
    : t < at('D1')
      ? '代码段：定时与时间流逝住在右边两条窄栏里，到点自己动，不换场景'
      : '办公段：左虚化代码+资料库卡片，中聊天，右成果——一句话到一份文件'
  $('hudTime').textContent = `${t.toFixed(1)}s / ${TOTAL.toFixed(1)}s · 100 BPM`
  document.querySelectorAll('[data-block]').forEach((node) => {
    node.classList.toggle('active', node.dataset.block === current.id)
  })
  style($('trackHead'), { left: `${((t / TOTAL) * 100).toFixed(3)}%` })

  $('flyLayer').innerHTML = fly
}

window.__sceneReady = true