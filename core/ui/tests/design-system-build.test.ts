import { describe, expect, it } from 'vitest'
import { build } from 'vite'

describe('standalone gallery build', () => {
  it('bundles Vue and uses relative asset URLs for hosting under any path', async () => {
    const result = await build({ configFile: 'vite.config.design-system.ts', build: { write: false } })
    const outputs = (Array.isArray(result) ? result : [result]).flatMap(item => item.output)
    expect(outputs.filter(item => item.type === 'asset').map(item => item.fileName)).toContain('design-system.html')
    const html = outputs.find(item => item.type === 'asset' && item.fileName === 'design-system.html')
    const js = outputs.find(item => item.type === 'chunk' && item.isEntry)
    expect(html && html.type === 'asset' ? String(html.source) : '').toMatch(/src="\.\/assets\//)
    expect(js && js.type === 'chunk' ? js.imports : []).not.toContain('vue')
  }, 30000)
})
