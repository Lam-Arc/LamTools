import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'

// user:"比如几何判定框与地图寻路模型，我不要这个透明窗口，你给我单独做一个界面。
// 最简单的界面，不需要有任何样式，就是把这件事儿给整明白"+
// (实验台必须是独立入口：有自己的 HTML 文档并注册进 vite 多入口，页面不依赖
//  透明覆盖层、不 import PetSurface/bridge/usePetRuntime——三块互不一起调试。)

test('pet-navlab 注册为独立 vite 入口且文件齐全', () => {
  assert.ok(existsSync(new URL('../pet-navlab.html', import.meta.url)), 'pet-navlab.html 必须存在')
  assert.ok(existsSync(new URL('../src/pet-navlab.ts', import.meta.url)), '入口脚本必须存在')
  assert.ok(
    existsSync(new URL('../../../core/ui/src/pet/ui/PetNavLab.vue', import.meta.url)),
    'PetNavLab.vue 必须存在',
  )
  const vite = readFileSync(new URL('../vite.config.ts', import.meta.url), 'utf8')
  assert.match(vite, /pet-navlab\.html/, 'vite 多入口必须注册 pet-navlab.html')
})

test('实验台不依赖透明覆盖层与穿透链路', () => {
  const entry = readFileSync(new URL('../src/pet-navlab.ts', import.meta.url), 'utf8')
  const entryImports = entry.split('\n').filter(l => l.trim().startsWith('import ')).join('\n')
  assert.doesNotMatch(entryImports, /PetSurface|usePetRuntime|bridge/, '入口不得 import 覆盖层组件或 bridge')
  const page = readFileSync(new URL('../../../core/ui/src/pet/ui/PetNavLab.vue', import.meta.url), 'utf8')
  const pageImports = page.split('\n').filter(l => l.trim().startsWith('import ')).join('\n')
  assert.doesNotMatch(pageImports, /PetSurface|usePetRuntime|pet-surface\.css|\.\.\/bridge\.ts/, '页面不得 import 覆盖层与穿透链路')
  assert.match(page, /new PetWorld\(/, '页面直接实例化引擎世界（纯模型）')
})
