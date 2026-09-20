import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const appSource = readFileSync(resolve(import.meta.dirname, '../src/App.vue'), 'utf8')

describe('mobile command dock host contract', () => {
  it('routes mode selection and shared app surfaces through the floating dock', () => {
    expect(appSource).toContain(':mode-options="mobileModeState.options"')
    expect(appSource).toContain(':active-mode-id="mobileModeState.activeId"')
    expect(appSource).toContain('@select-mode="lamToolsAppRef?.selectAppModeByKey($event)"')
    expect(appSource).toContain('@open-search="lamToolsAppRef?.openSearch()"')
    expect(appSource).toContain('@open-settings="lamToolsAppRef?.openSettings()"')
    expect(appSource).toContain('@open-account="accessPanelOpen = true"')
  })

  it('shows the active account identity without making login mandatory', () => {
    expect(appSource).toContain("accountClient.value?.session?.username || '登录 / 账号'")
    expect(appSource).toContain('accessPanelOpen.value = false')
  })
})
