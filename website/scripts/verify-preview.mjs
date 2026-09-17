import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

const baseUrl = process.argv[2] || 'http://127.0.0.1:5199'
const artifacts = resolve('artifacts')
await mkdir(artifacts, { recursive: true })

const browser = await chromium.launch({ headless: true })
const findings = {
  consoleErrors: [],
  pageErrors: [],
  apiRequests: [],
  webSockets: [],
}

function monitor(page, prefix = '') {
  page.on('console', (message) => {
    if (message.type() === 'error') findings.consoleErrors.push(`${prefix}${message.text()}`)
  })
  page.on('pageerror', (error) => findings.pageErrors.push(`${prefix}${error.message}`))
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr' || url.pathname.startsWith('/api/')) {
      findings.apiRequests.push(`${prefix}${request.method()} ${url.pathname}`)
    }
  })
  page.on('websocket', (socket) => findings.webSockets.push(`${prefix}${socket.url()}`))
}

async function getPreviewFrame(page) {
  await page.locator('.product-preview-frame').waitFor({ state: 'attached', timeout: 10_000 })
  await page.waitForFunction(() => (
    document.querySelector('.product-preview-frame')?.contentDocument?.querySelector('.workspace-shell')
  ), null, { timeout: 10_000 })
  const frame = page.frames().find((candidate) => {
    try {
      return new URL(candidate.url()).pathname.endsWith('/preview.html')
    } catch {
      return false
    }
  })
  if (!frame) throw new Error('Sunday product preview iframe did not mount')
  return frame
}

function rectInside(rect, viewport, tolerance = 1) {
  return rect.left >= -tolerance
    && rect.top >= -tolerance
    && rect.right <= viewport.width + tolerance
    && rect.bottom <= viewport.height + tolerance
}

async function inspect(page, label) {
  const frame = await getPreviewFrame(page)
  const host = await page.evaluate(() => ({
    theme: document.documentElement.dataset.siteTheme,
    pageScrollY: Math.round(window.scrollY),
    title: document.title,
    heading: document.querySelector('h1')?.textContent?.replace(/\s+/g, ' ').trim(),
    parentHasCoreOverlay: Boolean(document.querySelector('body > .workspace-shell, body > .settings-page')),
    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    overflowingElements: Array.from(document.querySelectorAll('body *')).flatMap((element) => {
      const rect = element.getBoundingClientRect()
      if (rect.left >= -1 && rect.right <= window.innerWidth + 1) return []
      const classes = typeof element.className === 'string' ? `.${element.className.trim().replace(/\s+/g, '.')}` : ''
      return [`${element.tagName.toLowerCase()}${classes} [${Math.round(rect.left)}, ${Math.round(rect.right)}]`]
    }).slice(0, 12),
    downloadPath: document.querySelector('#download a[download]')?.getAttribute('href'),
    iconReady: Array.from(document.querySelectorAll('img')).every((image) => image.complete && image.naturalWidth > 0),
  }))
  const embedded = await frame.evaluate(() => {
    const toRect = (element) => {
      if (!element) return null
      const rect = element.getBoundingClientRect()
      return {
        left: Math.round(rect.left * 10) / 10,
        top: Math.round(rect.top * 10) / 10,
        right: Math.round(rect.right * 10) / 10,
        bottom: Math.round(rect.bottom * 10) / 10,
        width: Math.round(rect.width * 10) / 10,
        height: Math.round(rect.height * 10) / 10,
      }
    }
    const shell = document.querySelector('.workspace-shell')
    const main = document.querySelector('.workspace-main')
    const composer = document.querySelector('.floating-composer')
    const thread = document.querySelector('.thread')
    const style = shell ? getComputedStyle(shell) : null
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      shell: toRect(shell),
      main: toRect(main),
      composer: toRect(composer),
      thread: thread ? {
        rect: toRect(thread),
        childCount: thread.children.length,
        textLength: thread.textContent?.trim().length || 0,
        scrollTop: Math.round(thread.scrollTop),
        scrollHeight: thread.scrollHeight,
        clientHeight: thread.clientHeight,
        alignContent: getComputedStyle(thread).alignContent,
      } : null,
      documentOverflow: document.documentElement.scrollWidth > window.innerWidth + 1
        || document.documentElement.scrollHeight > window.innerHeight + 1,
      iconReady: Array.from(document.querySelectorAll('img')).every((image) => image.complete && image.naturalWidth > 0),
      coreTheme: style ? {
        main: style.getPropertyValue('--theme-main-background').trim(),
        text: style.getPropertyValue('--theme-main-text').trim(),
      } : null,
    }
  })
  const artifactScrollY = await page.evaluate(() => window.scrollY)
  await page.screenshot({ path: resolve(artifacts, `${label}.png`), fullPage: true })
  await page.locator('.product-stage').screenshot({ path: resolve(artifacts, `${label}-stage.png`) })
  await page.evaluate((top) => {
    const previous = document.documentElement.style.scrollBehavior
    document.documentElement.style.scrollBehavior = 'auto'
    window.scrollTo({ top, behavior: 'auto' })
    document.documentElement.style.scrollBehavior = previous
  }, artifactScrollY)

  const snapshot = {
    ...host,
    productAppMounted: Boolean(embedded.shell),
    previewContained: Boolean(
      embedded.shell
      && embedded.main
      && embedded.composer
      && rectInside(embedded.shell, embedded.viewport)
      && rectInside(embedded.main, embedded.viewport)
      && rectInside(embedded.composer, embedded.viewport)
    ),
    embedded,
  }
  return snapshot
}

async function inspectSettingsContainment(page, label) {
  await page.goto(baseUrl, { waitUntil: 'networkidle' })
  const stage = page.locator('.product-stage')
  await stage.scrollIntoViewIfNeeded()
  const frame = await getPreviewFrame(page)
  const hostScrollBefore = await page.evaluate(() => Math.round(window.scrollY))
  await frame.getByRole('button', { name: '打开设置', exact: true }).click()
  await frame.locator('.settings-page').waitFor({ state: 'visible', timeout: 10_000 })
  const result = await frame.evaluate(() => {
    const page = document.querySelector('.settings-page')
    const rect = page?.getBoundingClientRect()
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      settings: rect ? {
        left: Math.round(rect.left * 10) / 10,
        top: Math.round(rect.top * 10) / 10,
        right: Math.round(rect.right * 10) / 10,
        bottom: Math.round(rect.bottom * 10) / 10,
        width: Math.round(rect.width * 10) / 10,
        height: Math.round(rect.height * 10) / 10,
      } : null,
    }
  })
  const hostScrollAfter = await page.evaluate(() => Math.round(window.scrollY))
  await stage.screenshot({ path: resolve(artifacts, `${label}-settings-stage.png`) })
  return {
    ...result,
    hostScrollBefore,
    hostScrollAfter,
    parentHasCoreOverlay: await page.evaluate(() => (
      Boolean(document.querySelector('body > .workspace-shell, body > .settings-page'))
    )),
    contained: Boolean(result.settings && rectInside(result.settings, result.viewport)),
  }
}

try {
  const desktop = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: 'dark' })
  monitor(desktop)
  await desktop.goto(baseUrl, { waitUntil: 'networkidle' })
  const graphite = await inspect(desktop, 'website-graphite-desktop')

  await desktop.getByRole('button', { name: '切换到象牙白主题' }).evaluate((element) => element.click())
  await desktop.waitForFunction(() => document.documentElement.dataset.siteTheme === 'ivory')
  await desktop.locator('.product-preview-frame').waitFor({ state: 'attached', timeout: 10_000 })
  await desktop.waitForTimeout(700)
  const ivory = await inspect(desktop, 'website-ivory-desktop')

  const wide = await browser.newPage({ viewport: { width: 2277, height: 1362 }, colorScheme: 'dark' })
  monitor(wide, '[wide] ')
  await wide.goto(baseUrl, { waitUntil: 'networkidle' })
  const wideSnapshot = await inspect(wide, 'website-graphite-wide')

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, colorScheme: 'dark' })
  monitor(mobile, '[mobile] ')
  await mobile.goto(baseUrl, { waitUntil: 'networkidle' })
  const mobileSnapshot = await inspect(mobile, 'website-graphite-mobile')

  const settingsPage = await browser.newPage({ viewport: { width: 2277, height: 1362 }, colorScheme: 'dark' })
  monitor(settingsPage, '[settings] ')
  const settings = await inspectSettingsContainment(settingsPage, 'website-graphite-wide')

  const snapshots = [graphite, ivory, wideSnapshot, mobileSnapshot]
  const summary = { graphite, ivory, wide: wideSnapshot, mobile: mobileSnapshot, settings, ...findings }
  const failed = [
    snapshots.some((snapshot) => !snapshot.productAppMounted),
    snapshots.some((snapshot) => !snapshot.previewContained),
    snapshots.some((snapshot) => snapshot.parentHasCoreOverlay),
    snapshots.some((snapshot) => snapshot.pageScrollY > 1),
    snapshots.some((snapshot) => snapshot.horizontalOverflow),
    snapshots.some((snapshot) => snapshot.embedded.documentOverflow),
    snapshots.some((snapshot) => !snapshot.iconReady || !snapshot.embedded.iconReady),
    graphite.theme !== 'graphite',
    ivory.theme !== 'ivory',
    !settings.contained,
    settings.parentHasCoreOverlay,
    Math.abs(settings.hostScrollAfter - settings.hostScrollBefore) > 1,
    findings.consoleErrors.length > 0,
    findings.pageErrors.length > 0,
    findings.apiRequests.length > 0,
    findings.webSockets.length > 0,
  ].some(Boolean)

  console.log(JSON.stringify(summary, null, 2))
  if (failed) process.exitCode = 1
} finally {
  await browser.close()
}
