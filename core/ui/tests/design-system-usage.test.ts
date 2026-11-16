import { describe, expect, it } from 'vitest'
import { componentImports, renderUsage } from '../../../scripts/ui-inventory.mjs'

describe('component usage index', () => {
  it('resolves aliases and relative component imports without inventing external components', () => {
    const imports = componentImports('core/ui/src/components/Example.vue', `
      import Switch from '@/components/SundaySwitch.vue'
      import Badge from './FileTypeBadge.vue'
      import External from 'package/Widget.vue'
    `)
    expect(imports).toEqual(['core/ui/src/components/SundaySwitch.vue', 'core/ui/src/components/FileTypeBadge.vue'])
    expect(componentImports('core/desktop/src/pet-navlab.ts', `import PetNavLab from '@/pet/ui/PetNavLab.vue'`)).toEqual(['core/ui/src/pet/ui/PetNavLab.vue'])
    const report = renderUsage([{ path: 'core/ui/src/components/Example.vue', imports }])
    expect(report).toContain('SundaySwitch.vue')
    expect(report).toContain('Example.vue')
    expect(report).not.toContain('package/Widget.vue')
    const gallery = renderUsage([{ path: 'core/ui/src/design-system/Gallery.vue', imports: ['core/ui/src/components/SundaySwitch.vue'] }])
    expect(gallery).toContain('预览入口')
    const lab = renderUsage([{ path: 'core/desktop/src/pet-navlab.ts', imports: ['core/ui/src/pet/ui/PetNavLab.vue'] }])
    expect(lab).toContain('预览入口')
    const production = renderUsage([{ path: 'core/ui/src/components/Example.vue', imports: ['core/ui/src/components/SundaySwitch.vue'] }])
    expect(production).not.toContain('预览入口')
  })
})
