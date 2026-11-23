// @vitest-environment node
import { expect, it } from 'vitest'
import { collectUiPaths } from '../../../scripts/ui-inventory.mjs'

// user:“全面盘点：梳理所有可见的组件、样式、布局、动效及交互”+(生成的类型声明不计入可见界面源码)。
it('excludes generated declarations from the UI source inventory', async () => {
  const paths: string[] = await collectUiPaths()
  expect(paths.some(path => path.endsWith('.d.ts'))).toBe(false)
  expect(paths).toContain('core/ui/src/components/CoreRuntimeMenu.vue')
})
