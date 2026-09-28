import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const mobileRoot = resolve(import.meta.dirname, '..')
const source = (relativePath: string): string => readFileSync(resolve(mobileRoot, relativePath), 'utf8')

const shellPlugin = source(
  'src-tauri/gen/android/app/src/main/java/com/lamtools/mobile/LamToolsShellPlugin.kt',
)
const filePaths = source('src-tauri/gen/android/app/src/main/res/xml/file_paths.xml')
const manifest = source('src-tauri/gen/android/app/src/main/AndroidManifest.xml')
const libSource = source('src-tauri/src/lib.rs')

/**
 * The update hand-off spans two processes: Android's downloader writes the APK,
 * the app verifies it, then the installer is asked to take that exact file.
 * These are the seams where 0.1.40 silently failed to install at all.
 */
describe('update install hand-off contract', () => {
  it('asks for the permission Android requires before an app may install', () => {
    expect(manifest).toContain('android.permission.REQUEST_INSTALL_PACKAGES')
  })

  it('looks for the APK where the download was written, not only in the cache', () => {
    // The system downloader writes to the app's external files dir; only the
    // in-process fallback uses the cache.
    expect(shellPlugin).toContain('setDestinationInExternalFilesDir(activity, null, "sunday-updates/$fileName")')
    expect(shellPlugin).toContain('private fun resolveUpdateFile(fileName: String): File')
    expect(shellPlugin).toContain('val file = resolveUpdateFile(fileName)')
    expect(shellPlugin).not.toContain('File(activity.cacheDir, "sunday-updates").canonicalFile')
  })

  it('declares the update directory to the FileProvider the installer reads through', () => {
    expect(filePaths).toContain('<external-files-path name="sunday_updates" path="sunday-updates/" />')
    expect(shellPlugin).toContain('"${activity.packageName}.fileprovider"')
    expect(shellPlugin).toMatch(/setDataAndType\(uri, "application\/vnd\.android\.package-archive"\)/)
    expect(shellPlugin).toContain('addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)')
  })

  it('guides the user to the unknown-apps setting instead of failing quietly', () => {
    expect(shellPlugin).toContain('activity.packageManager.canRequestPackageInstalls()')
    expect(shellPlugin).toContain('Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)')
    expect(shellPlugin).toContain('.put("needsPermission", true)')
    // The host turns that result into copy the update card can show.
    expect(libSource).toContain('result.get("needsPermission").and_then(Value::as_bool)')
    expect(libSource).toContain('"needs_permission": true')
  })
})
