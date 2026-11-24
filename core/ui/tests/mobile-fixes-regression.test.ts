import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * user:“都修”+(这一轮手机端的五个坑：附件撑高后引导块压标题、灯箱关闭键被挤出屏幕、
 * 手机设置里的桌宠分区报错、底部导航被手势条压住、调试包过大)。
 * 这些是布局/宿主链路，jsdom 没有真实排版，用源码断言锁住关键约定。
 */
const read = (rel: string) => readFileSync(resolve(__dirname, '..', rel), 'utf8')

describe('手机端这一轮的修复', () => {
  it('有附件时收起空会话引导块，避免压住顶部标题', () => {
    const source = read('src/app/LamToolsApp.vue')
    expect(source).toMatch(/v-if="isEmptySession && !pendingAttachments\.length"/)
  })

  it('灯箱窄屏下头部可横向滚动、关闭键粘在右缘，并且系统返回先关灯箱', () => {
    const source = read('src/preview/PreviewLightbox.vue')
    expect(source).toMatch(/@media \(max-width: 640px\)[\s\S]*?\.preview-lightbox__header \{[^}]*overflow-x: auto/)
    expect(source).toMatch(/\.preview-lightbox__close \{[^}]*position: sticky/)
    expect(source).toContain("window.addEventListener('sunday:back', onSystemBack)")
    expect(source).toMatch(/function onSystemBack[\s\S]*?requestClose\(\)/)
  })

  it('手机设置不列桌宠分区（宿主没有那些命令）', () => {
    const source = read('src/components/CoreSettings.vue')
    expect(source).toMatch(/mobileHiddenSettings = new Set\(\['pet'\]\)/)
    expect(source).toMatch(/props\.commandShellPlatform === 'mobile'[\s\S]*?CORE_SETTINGS_SECTIONS\.filter/)
  })

  it('宿主上报底部安全区，界面取 max(native, env)', () => {
    const kotlin = read('../android-host/android-src/com/lamtools/sunday/core/KeyboardBridge.kt')
    expect(kotlin).toContain('nativePublishInsets(keyboard, top, bottom)')
    expect(kotlin).toContain('WindowInsetsCompat.Type.navigationBars()')

    const rust = read('../android-host/src-tauri/src/lib.rs')
    expect(rust).toContain('fn publish_insets(keyboard: i64, top: i64, bottom: i64)')
    expect(rust).toContain('"bottom": bottom')

    const android = read('src/core-app/main-android.ts')
    expect(android).toContain("'--native-safe-area-bottom'")

    // 安全区定义在根上：底部导航在壳外，从 .workspace-shell 里读不到这个变量。
    const css = read('src/styles/variables.css')
    expect(css).toMatch(/--safe-area-bottom: max\(var\(--native-safe-area-bottom, 0px\), env\(safe-area-inset-bottom/)
  })

  it('调试包去掉 .so 里的调试符号（安装包从 455MB 的量级降下来）', () => {
    const cargo = read('../android-host/src-tauri/Cargo.toml')
    expect(cargo).toMatch(/\[profile\.dev\][\s\S]*?strip = "debuginfo"/)
  })

  it('runs Android page extraction through the native callback without enabling release debugging', () => {
    const kotlin = read('../android-host/android-src/com/lamtools/sunday/core/BrowserBridge.kt')
    expect(kotlin).not.toContain('WebView.setWebContentsDebuggingEnabled(true)')
    expect(kotlin).not.toContain('addJavascriptInterface')
    expect(kotlin).toMatch(/evaluateJavascript\(script\)\s*\{/)
  })

  it('checks a healthy remote Core for liveness and publishes both probe outcomes', () => {
    const host = read('../android-host/src-tauri/src/p2p_bridge.rs')
    const emitter = host.slice(host.indexOf('pub fn start_emitter'), host.indexOf('fn layers_json'))
    expect(emitter).not.toMatch(/&&\s*!state\.core_ready\.load/)
    expect(emitter).toContain('"namespace": "core.onboarding"')
    expect(emitter).toMatch(/core_ready\.store\(ready,/)
  })
})
