import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../src/pairing/PairingScreen.vue', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const templateEnd = source.indexOf('\n</template>\n\n<script setup')
const template = source.slice(source.indexOf('<template>'), templateEnd + '\n</template>'.length)

describe('PairingScreen account entry', () => {
  it('keeps the default account card limited to credentials and authentication actions', () => {
    const moreStart = template.indexOf('<section v-if="moreOpen"')
    const defaultView = template.slice(0, moreStart)
    const advancedView = template.slice(moreStart)

    expect(defaultView).toContain('autocomplete="username"')
    expect(defaultView).toContain('autocomplete="current-password"')
    expect(defaultView).toContain('确认登录')
    expect(defaultView).toContain('转到注册')
    expect(defaultView).not.toContain('id="pairing-code"')
    expect(defaultView).not.toContain('id="gateway-url"')
    expect(advancedView).toContain('id="pairing-code"')
    expect(advancedView).toContain('id="gateway-url"')
    expect(advancedView).toContain('id="server-url"')
  })

  it('keeps advanced connection methods behind the More disclosure', () => {
    expect(template).toContain(':aria-expanded="moreOpen"')
    expect(template).toContain('@click="moreOpen = !moreOpen"')
    expect(template).toContain('<section v-if="moreOpen"')
  })

  it('supports a non-dismissible first-login card', () => {
    expect(template).toContain('v-if="closable"')
  })

  it('replaces the login card title when registration is selected', () => {
    expect(template).toContain("authMode === 'login' ? '登录 LamTools' : '注册 LamTools'")
  })

  it('shows the signed-in account device topology before advanced pairing controls', () => {
    const devices = template.indexOf('设备与工作环境')
    const more = template.indexOf('pairing-screen__more-toggle')

    expect(devices).toBeGreaterThan(-1)
    expect(devices).toBeLessThan(more)
    expect(template).toContain("device.online ? '在线' : '离线'")
    expect(template).toContain("$emit('workspace-select', device.workspaceId)")
  })

  it('shares the mobile host account state and actions with Core settings', () => {
    expect(appSource).toContain(':account-context="accountContext"')
    expect(appSource).toContain('@account-submit="authenticateCoreAccount"')
    expect(appSource).toContain('@account-logout="logoutAccount"')
  })
})
