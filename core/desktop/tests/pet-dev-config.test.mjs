import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

// user:“主窗口不可拖动”+(pet-dev 配置用 app.windows 整段替换基础配置的窗口定义，
//  一旦丢了字段，自绘标题栏的拖动行为就失效。窗口定义必须完全走基础配置，
//  dev 配置只保留独立标识与端口。)
const base = JSON.parse(
  readFileSync(new URL('../src-tauri/tauri.conf.json', import.meta.url), 'utf8'),
)
const dev = JSON.parse(
  readFileSync(new URL('../tauri.pet-dev.conf.json', import.meta.url), 'utf8'),
)

test('pet-dev 配置不覆盖 app.windows（主窗口/覆盖层定义完全走基础配置）', () => {
  assert.equal(dev.app?.windows, undefined)
  assert.ok(Array.isArray(base.app.windows))
  assert.ok(base.app.windows.length >= 2)
})

test('pet-dev 配置保留独立标识与独立端口（不碰正式实例）', () => {
  assert.equal(dev.productName, 'Sunday Pet Dev')
  assert.equal(dev.identifier, 'com.lamtools.lamcore.petdev')
  assert.equal(dev.build.devUrl, 'http://127.0.0.1:5299')
  assert.match(dev.build.beforeDevCommand, /dev:pet/)
})
