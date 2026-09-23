import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const mobileRoot = resolve(import.meta.dirname, '..')
const source = (relativePath: string): string => readFileSync(resolve(mobileRoot, relativePath), 'utf8')

const appSource = source('src/App.vue')
const insetSource = source('src/native/windowInsets.ts')
const rustSource = source('src-tauri/src/lib.rs')
const rustInsetSource = source('src-tauri/src/window_insets.rs')
const androidPluginSource = source(
  'src-tauri/gen/android/app/src/main/java/com/lamtools/mobile/LamToolsWindowInsetsPlugin.kt',
)
const shellCss = readFileSync(resolve(mobileRoot, '../ui/src/styles/workspace-shell.css'), 'utf8')
const topBarSource = readFileSync(resolve(mobileRoot, '../ui/src/components/MobileTopBar.vue'), 'utf8')
const sharedAppSource = readFileSync(resolve(mobileRoot, '../ui/src/app/LamToolsApp.vue'), 'utf8')
const titleBarSource = readFileSync(resolve(mobileRoot, '../ui/src/components/TitleBar.vue'), 'utf8')

describe('mobile layout native bridge contract', () => {
  it('keeps the mobile drawer at its full width while open', () => {
    expect(shellCss).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.drawer-left \{[\s\S]*?width: var\(--sidebar-width\);[\s\S]*?max-width: var\(--sidebar-width\);/,
    )
  })

  it('publishes Android edge-to-edge insets in CSS pixels', () => {
    expect(androidPluginSource).toContain('WindowInsetsCompat.Type.statusBars()')
    expect(androidPluginSource).toContain('WindowInsetsCompat.Type.displayCutout()')
    expect(androidPluginSource).toContain('displayMetrics.density')
    expect(androidPluginSource).toContain('window insets unavailable')
    expect(androidPluginSource).toContain('if (density <= 0f)')
    expect(androidPluginSource).not.toContain('coerceAtLeast(1f)')
    expect(androidPluginSource).toContain('value.toDouble() / density')
    expect(rustSource).toContain('LamToolsWindowInsetsPlugin')
    expect(rustInsetSource).toContain('fn window_insets_get(')
    expect(rustSource).toContain('window_insets::window_insets_get')
    expect(insetSource).toContain("invoke<NativeWindowInsets>('window_insets_get')")
  })

  it('feeds the native top inset into the shared header offset', () => {
    expect(appSource).toContain('observeNativeWindowInsets(syncNativeWindowInsets)')
    expect(appSource).toContain("--native-safe-area-top")
    expect(appSource).toContain('document.documentElement.style.removeProperty(\'--native-safe-area-top\')')
    expect(topBarSource).toContain('var(--mobile-header-offset, env(safe-area-inset-top, 0px))')
  })

  it('uses the mobile top bar without mounting desktop window chrome', () => {
    expect(appSource).toContain('<MobileTopBar')
    expect(sharedAppSource).toContain(':hide-on-mobile="runtime.platform === \'mobile\'"')
    expect(titleBarSource).toContain('!props.hideOnMobile && (isTauri.value || props.showInPreview === true)')
  })
})
