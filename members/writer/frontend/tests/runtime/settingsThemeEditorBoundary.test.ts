import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewSource = readFileSync(resolve('src/views/SettingsView.vue'), 'utf8')

test('settings delegates its shell layout to the shared SettingsShell', () => {
  assert.match(viewSource, /SettingsShell/)
  assert.match(viewSource, /<SettingsShell[\s\S]*:sections="settingsSections"[\s\S]*:settings-theme-style="settingsThemeStyle"[\s\S]*@close="goBack"/)
  assert.match(viewSource, /<template #notice>[\s\S]*noticeText/)
  assert.match(viewSource, /<template #default="\{ activeSection: shellActiveSection \}">/)
  assert.match(viewSource, /id: 'model-api'/)
  assert.match(viewSource, /id: 'ui-system'/)
  assert.match(viewSource, /id: 'permissions'/)
  assert.doesNotMatch(viewSource, /<div class="settings-page"/)
  assert.doesNotMatch(viewSource, /<aside class="settings-sidebar"/)
  assert.doesNotMatch(viewSource, /<nav class="settings-nav"/)
  assert.doesNotMatch(viewSource, /<main class="settings-main"/)
})

test('settings delegates four-area theme editing to the shared ThemeEditor', () => {
  assert.match(viewSource, /import\s*\{[\s\S]*?ThemeEditor[\s\S]*?\}\s*from '@lamtools\/ui'/)
  assert.match(viewSource, /<ThemeEditor[\s\S]*:get-stops="gradientStops"[\s\S]*:get-angle="themeAngle"[\s\S]*:get-opacity="themeOpacity"[\s\S]*:get-text-color="themeTextColor"/)
  assert.match(viewSource, /<ThemeEditor[\s\S]*:presets="writerThemePresets"[\s\S]*:presets-by-group="presetsByGroup"/)
  assert.match(viewSource, /@update-stops="updateThemeStops"/)
  assert.match(viewSource, /@update-angle="updateThemeAngle"/)
  assert.match(viewSource, /@update-opacity="updateThemeOpacity"/)
  assert.match(viewSource, /@update-text-color="updateThemeTextColor"/)
  assert.match(viewSource, /@add-stop="addGradientStop"/)
  assert.match(viewSource, /@remove-stop="removeGradientStop"/)
  assert.match(viewSource, /@sort-stops="sortGradientStops"/)
  assert.doesNotMatch(viewSource, /<section class="theme-area-card">/)
})

test('settings keeps Writer-owned theme persistence, presets, and swapping', () => {
  assert.match(viewSource, /uiSystem:\s*'lamwriter\.ui'/)
  assert.match(viewSource, /const writerThemePresets: WriterThemePreset\[\]/)
  assert.match(viewSource, /@apply-preset="applyThemePreset"/)
  assert.match(viewSource, /@reset-theme="resetTheme"/)
  assert.match(viewSource, /@click="swapBackdropAndMainTheme"/)
  assert.match(viewSource, /function swapBackdropAndMainTheme\(\)/)
})
