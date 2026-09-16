import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'
import { inflateSync } from 'node:zlib'

import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')

function alphaBounds(path: string, threshold = 8): { width: number; height: number; bounds: [number, number, number, number] | null } {
  const bytes = readFileSync(resolve(process.cwd(), path))
  expect(bytes.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
  const width = bytes.readUInt32BE(16)
  const height = bytes.readUInt32BE(20)
  expect(bytes[24]).toBe(8)
  expect(bytes[25]).toBe(6)

  const idat: Buffer[] = []
  let offset = 8
  while (offset + 12 <= bytes.length) {
    const length = bytes.readUInt32BE(offset)
    const type = bytes.subarray(offset + 4, offset + 8).toString('ascii')
    const data = bytes.subarray(offset + 8, offset + 8 + length)
    if (type === 'IDAT') idat.push(data)
    offset += 12 + length
    if (type === 'IEND') break
  }

  const scanlines = inflateSync(Buffer.concat(idat))
  const rowBytes = width * 4
  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1
  let previous = Buffer.alloc(rowBytes)
  let scanOffset = 0
  const paeth = (a: number, b: number, c: number) => {
    const p = a + b - c
    const pa = Math.abs(p - a)
    const pb = Math.abs(p - b)
    const pc = Math.abs(p - c)
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c
  }

  for (let y = 0; y < height; y += 1) {
    const filter = scanlines[scanOffset++]
    const row = Buffer.from(scanlines.subarray(scanOffset, scanOffset + rowBytes))
    scanOffset += rowBytes
    for (let index = 0; index < rowBytes; index += 1) {
      const left = index >= 4 ? row[index - 4] : 0
      const up = previous[index]
      const upLeft = index >= 4 ? previous[index - 4] : 0
      const value = row[index]
      row[index] = filter === 0
        ? value
        : filter === 1
          ? (value + left) & 255
          : filter === 2
            ? (value + up) & 255
            : filter === 3
              ? (value + Math.floor((left + up) / 2)) & 255
              : (value + paeth(left, up, upLeft)) & 255
    }
    for (let x = 0; x < width; x += 1) {
      if (row[x * 4 + 3] <= threshold) continue
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
    previous = row
  }

  return {
    width,
    height,
    bounds: maxX < 0 ? null : [minX, minY, maxX + 1, maxY + 1],
  }
}

describe('Sunday ivory and graphite brand assets', () => {
  it('keeps every source logo free of gradients', () => {
    const component = read('src/components/SundayLogo.vue')
    const mark = read('src/assets/sunday-mark.svg')
    const lightMark = read('src/assets/sunday-mark-light.svg')
    const darkMark = read('src/assets/sunday-mark-dark.svg')
    const appIcon = read('src/assets/sunday-app-icon.svg')
    const lightAppIcon = read('src/assets/sunday-app-icon-light.svg')
    const desktopHtml = read('../desktop/index.html')
    const startupMark = desktopHtml.match(/<span class="startup-splash__mark"[\s\S]*?<\/span>/)?.[0] || ''

    for (const source of [component, mark, lightMark, darkMark, appIcon, lightAppIcon]) {
      expect(source).not.toMatch(/(?:linear|radial)Gradient|url\(#/i)
      expect(source).toContain('viewBox="0 0 1024 1024"')
      expect(source).not.toContain('M1172 440')
      expect(source).not.toContain('M1209 700')
    }
    for (const source of [component, mark, lightMark, darkMark]) {
      expect(source).toContain('cx="367.5" cy="421.7" rx="64.1" ry="63.7"')
      expect(source).toContain('M599.8 442.4C647.1 408.3 694.7 405.8 726.3 435.3')
      expect(source).toContain('M318.1 581.4C410.9 697.3 603.9 694.6 703.4 582.6')
    }
    expect(component).toContain('fill="currentColor"')
    expect(component).toContain('ref="eyeEl"')
    expect(component).toContain('ref="winkEl"')
    expect(component).toContain('ref="smileEl"')
    expect(component).toContain("surfaceTheme === 'light' ? appIconLightUrl : appIconDarkUrl")
    expect(mark).toContain('#2E3138')
    expect(lightMark).toContain('#2E3138')
    expect(darkMark).toContain('#FBF7F0')
    expect(appIcon).toContain('href="sunday-app-icon-dark-display.png"')
    expect(lightAppIcon).toContain('href="sunday-app-icon-light-display.png"')
    expect(startupMark).not.toContain('sunday-app-icon-dark-display.png')
    expect(startupMark).not.toContain('sunday-app-icon-light-display.png')
    expect(startupMark).toContain('id="startup-icon-frame"')
    expect(startupMark).toContain('<svg')
  })

  it('retains the lossless 1254px reference artwork for complete app-icon surfaces', () => {
    const dark = readFileSync(resolve(process.cwd(), 'src/assets/sunday-app-icon-dark.png'))
    const light = readFileSync(resolve(process.cwd(), 'src/assets/sunday-app-icon-light.png'))

    expect(dark.subarray(1, 4).toString('ascii')).toBe('PNG')
    expect(light.subarray(1, 4).toString('ascii')).toBe('PNG')
    expect(dark.readUInt32BE(16)).toBe(1254)
    expect(dark.readUInt32BE(20)).toBe(1254)
    expect(light.readUInt32BE(16)).toBe(1254)
    expect(light.readUInt32BE(20)).toBe(1254)
    expect(createHash('sha256').update(dark).digest('hex')).toBe('43baa9ec01d1f571852e3dc86463b27e39a077ff43c49523d6bfb27f12768291')
    expect(createHash('sha256').update(light).digest('hex')).toBe('dba8a5508c294093fb3723bfe9417a04564bf797a2bf61121247464db0bd0087')
  })

  it('keeps normalized display masters inside the 90–91% meaningful coverage band', () => {
    for (const path of [
      'src/assets/sunday-app-icon-dark-display.png',
      'src/assets/sunday-app-icon-light-display.png',
    ]) {
      const image = alphaBounds(path)
      expect(image.width).toBe(1254)
      expect(image.height).toBe(1254)
      expect(image.bounds).not.toBeNull()
      const [left, top, right, bottom] = image.bounds as [number, number, number, number]
      expect((right - left) / image.width).toBeGreaterThanOrEqual(0.89)
      expect((right - left) / image.width).toBeLessThanOrEqual(0.92)
      expect((bottom - top) / image.height).toBeGreaterThanOrEqual(0.89)
      expect((bottom - top) / image.height).toBeLessThanOrEqual(0.92)
    }
  })

  it('passes the resolved application theme into the title-bar icon', () => {
    const app = read('src/app/LamToolsApp.vue')
    const titleBar = read('src/components/TitleBar.vue')

    expect(app).toContain(':effective-theme-mode="effectiveThemeMode"')
    expect(titleBar).toContain(':surface-theme="props.effectiveThemeMode"')
    expect(titleBar).toContain("effectiveThemeMode?: 'light' | 'dark'")
  })

  it('uses the same explicit border token for the main boundary and composer', () => {
    const layout = read('src/styles/layout.css')
    expect(layout).toMatch(/\.workspace-main\s*\{[\s\S]*?border: 1px solid var\(--theme-main-border\);/)
    expect(layout).toMatch(/\.floating-composer\s*\{[\s\S]*?border: 1px solid var\(--theme-main-border\);/)
    expect(layout).toMatch(/\.floating-composer:focus-within\s*\{\s*border-color: var\(--theme-main-border\);/)
  })

  it('keeps the workspace fallback on the flat dark Sunday surface map', () => {
    const shell = read('src/styles/workspace-shell.css')
    const fallback = shell.match(/\.workspace-shell\s*\{([\s\S]*?)\n\s*position: fixed;/)?.[1] || ''
    expect(fallback).toContain('--theme-backdrop-background: #3A3B3F;')
    expect(fallback).toContain('--theme-main-background: #1B1D22;')
    expect(fallback).toContain('--theme-main-border: #818289;')
    expect(fallback).toContain('--theme-composer-background: #22242A;')
    expect(fallback).toContain('--theme-control-background: #FBF7F0;')
    expect(fallback).toContain('--theme-control-solid: #FBF7F0;')
    expect(fallback).toContain('--theme-control-text: #2E3138;')
    expect(fallback).not.toMatch(/(?:linear|radial)-gradient/i)
  })

  it('ships regenerated ICO and ICNS icon containers', () => {
    const ico = readFileSync(resolve(process.cwd(), '../desktop/src-tauri/icons/icon.ico'))
    const icns = readFileSync(resolve(process.cwd(), '../desktop/src-tauri/icons/icon.icns'))
    const backendIco = readFileSync(resolve(process.cwd(), '../desktop/app-icon.ico'))
    const legacyUiIco = readFileSync(resolve(process.cwd(), '../desktop/ui/public/app-icon.ico'))
    const uiIco = readFileSync(resolve(process.cwd(), 'public/app-icon.ico'))
    const entryCount = ico.readUInt16LE(4)
    const sizes = Array.from({ length: entryCount }, (_, index) => {
      const width = ico[6 + index * 16]
      return width === 0 ? 256 : width
    })
    expect([...ico.subarray(0, 4)]).toEqual([0, 0, 1, 0])
    expect(sizes.sort((left, right) => left - right)).toEqual([64, 80, 96, 128, 192, 256])
    expect(icns.subarray(0, 4).toString('ascii')).toBe('icns')
    expect(backendIco.equals(ico)).toBe(true)
    expect(legacyUiIco.equals(ico)).toBe(true)
    expect(uiIco.equals(ico)).toBe(true)
  })
})
