// user:“TypeError: Failed to fetch dynamically imported module”+(桌面插件资源应使用实际后台地址，不走前端开发服务器的固定端口)。
import { afterEach, expect, it } from 'vitest'
import { pluginAssetUrl, setPluginAssetBase } from '../src/plugins/assets'
afterEach(() => setPluginAssetBase(null))
it('resolves plugin modules and styles against the actual desktop backend', () => {
  setPluginAssetBase('http://127.0.0.1:50272')
  expect(pluginAssetUrl('/api/core/plugin-system/network-exploration/assets/ui/page.mjs')).toBe('http://127.0.0.1:50272/api/core/plugin-system/network-exploration/assets/ui/page.mjs')
  expect(pluginAssetUrl('/api/core/plugin-system/network-exploration/assets/ui/style.css')).toContain(':50272/')
})
it('keeps normal same-origin browser behavior without a desktop backend', () => {
  expect(pluginAssetUrl('/api/core/plugin-system/demo/assets/page.mjs')).toBe('/api/core/plugin-system/demo/assets/page.mjs')
})
