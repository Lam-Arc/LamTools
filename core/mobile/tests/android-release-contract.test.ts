import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const strings = readFileSync(
  new URL('../android/app/src/main/res/values/strings.xml', import.meta.url),
  'utf8',
)

describe('Android release identity contract', () => {
  it('uses Sunday for the launcher and activity labels', () => {
    expect(strings).toContain('<string name="app_name">Sunday</string>')
    expect(strings).toContain('<string name="title_activity_main">Sunday</string>')
    expect(strings).not.toContain('<string name="app_name">LamTool</string>')
    expect(strings).not.toContain('<string name="title_activity_main">LamTool</string>')
  })
})
