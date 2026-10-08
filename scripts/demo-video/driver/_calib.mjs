import { chromium } from 'playwright'
import { applyDemoLayout, assertForeground } from './sunday.mjs'
const browser = await chromium.connectOverCDP('http://127.0.0.1:9222', { timeout: 20000 })
const context = browser.contexts()[0]
const page = context.pages()[0]
await assertForeground(page)
console.log('native geometry:', JSON.stringify(await page.evaluate(() => ({ dpr: window.devicePixelRatio, inner: [innerWidth, innerHeight], screen: [screen.width, screen.height] }))))
for (const dsf of [1, 1.85]) {
  const layout = { width: 1380, height: 776, dsf }
  console.log(`--- layout ${layout.width}x${layout.height} dsf=${dsf}`)
  console.log('   page says:', JSON.stringify(await applyDemoLayout(context, page, layout)))
  // frame size
  const cdp = await context.newCDPSession(page)
  await cdp.send('Page.enable')
  let size = '?', frames = 0
  cdp.on('Page.screencastFrame', async (f) => {
    frames++
    if (size === '?') {
      const buf = Buffer.from(f.data, 'base64'); let off = 2
      while (off < buf.length - 9) {
        if (buf[off] !== 0xff) { off++; continue }
        const m = buf[off+1], len = buf.readUInt16BE(off+2)
        if (m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc) { size = `${buf.readUInt16BE(off+7)}x${buf.readUInt16BE(off+5)}`; break }
        off += 2 + len
      }
    }
    cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {})
  })
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: 4096, maxHeight: 4096, everyNthFrame: 1 })
  await page.evaluate(() => { if (!window.__demoTicker) { const n = document.createElement('div'); n.setAttribute('data-demo-ticker','1'); n.style.cssText='position:fixed;left:0;top:0;width:2px;height:2px;pointer-events:none;z-index:2147483647;opacity:0.01;background:#fff;will-change:transform'; document.documentElement.appendChild(n); let i=0; const step=()=>{i=(i+1)%4096;n.style.transform='translate3d('+i+'px,0,0)';window.__demoTicker=requestAnimationFrame(step)}; window.__demoTicker=requestAnimationFrame(step) } })
  await new Promise(r => setTimeout(r, 2200))
  await cdp.send('Page.stopScreencast').catch(() => {})
  await cdp.detach()
  console.log(`   frames=${frames} size=${size}`)
  // click check: model trigger (right side) and composer textarea (bottom)
  for (const sel of ['.composer-input-wrap textarea', '.core-model-thinking-menu__trigger']) {
    const loc = page.locator(sel).first()
    const box = await loc.boundingBox().catch(() => null)
    if (!box) { console.log(`   ${sel}: no box`); continue }
    let ok = false
    try { await loc.click({ timeout: 3500 }); ok = true } catch (e) { ok = String(e.message).split('\n')[0] }
    const state = await page.evaluate(() => ({
      active: document.activeElement?.tagName,
      menu: document.querySelectorAll('.core-model-thinking-menu__panel').length,
    }))
    console.log(`   ${sel}: box=(${Math.round(box.x)},${Math.round(box.y)}) click=${ok} state=${JSON.stringify(state)}`)
    if (state.menu) await page.keyboard.press('Escape')
  }
}
await browser.close()
