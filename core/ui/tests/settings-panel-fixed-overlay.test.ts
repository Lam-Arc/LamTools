import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * user:“模型配置界面点击添加供应商后，背景变为黑色，但是配置卡片未出现，p0 级 bug”+
 * (根因不是卡片没渲染，而是入场动画 fill-mode: both 结束后留着一个单位矩阵 transform；
 *  transform 会把 position: fixed 的子孙改成相对设置面板定位，供应商卡片被推到屏幕外。
 *  这里锁住两件事：动画不再保留填充值；窄目录里的编辑器居中显示、保存键不被底部导航挡住)。
 */
const motionCss = readFileSync(resolve(__dirname, '../src/styles/sunday-motion.css'), 'utf8')
const catalogSource = readFileSync(resolve(__dirname, '../src/components/CoreModelCatalog.vue'), 'utf8')

describe('设置面板动画不会把 fixed 浮层带偏', () => {
  it('入场动画用 backwards，不用 both（both 会留下 transform）', () => {
    const shared = motionCss.match(/\.sunday-motion-row,[\s\S]*?\}/)
    expect(shared).not.toBeNull()
    expect(shared![0]).toContain('backwards')
    expect(shared![0]).not.toMatch(/\bboth\b/)
  })

  it('手机上的供应商编辑器居中显示，而不是贴底', () => {
    const style = catalogSource.match(/const overlayInspectorStyle = computed[\s\S]*?\n\}\)/)
    expect(style).not.toBeNull()
    expect(style![0]).toContain('narrowCatalog.value')
    expect(style![0]).toContain("top: '50%'")
    expect(style![0]).toContain("transform: 'translate(-50%, -50%)'")
    expect(style![0]).toContain("maxHeight: 'calc(100dvh - 150px)'")
  })
})
