import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'

// user:"现在做方块人的动画，用独立的 HTML 给我展示出来，然后底下要可以控制动作组"+
// (动画实验台必须是独立入口：自己的 HTML、注册进 vite 多入口，页面不依赖透明
//  覆盖层、bridge、引擎世界——方块人动画单独调试。)

test('pet-animlab 注册为独立 vite 入口且文件齐全', () => {
  assert.ok(existsSync(new URL('../pet-animlab.html', import.meta.url)), 'pet-animlab.html 必须存在')
  assert.ok(existsSync(new URL('../src/pet-animlab.ts', import.meta.url)), '入口脚本必须存在')
  assert.ok(
    existsSync(new URL('../../../core/ui/src/pet/ui/PetAnimLab.vue', import.meta.url)),
    'PetAnimLab.vue 必须存在',
  )
  const vite = readFileSync(new URL('../vite.config.ts', import.meta.url), 'utf8')
  assert.match(vite, /pet-animlab\.html/, 'vite 多入口必须注册 pet-animlab.html')
})

test('动画实验台只装方块人姿态，不依赖覆盖层与引擎世界', () => {
  const entry = readFileSync(new URL('../src/pet-animlab.ts', import.meta.url), 'utf8')
  const entryImports = entry.split('\n').filter(line => line.trim().startsWith('import ')).join('\n')
  assert.doesNotMatch(entryImports, /PetSurface|usePetRuntime|bridge|PetWorld/, '入口不得 import 覆盖层或引擎世界')
  const page = readFileSync(new URL('../../../core/ui/src/pet/ui/PetAnimLab.vue', import.meta.url), 'utf8')
  const pageImports = page.split('\n').filter(line => line.trim().startsWith('import ')).join('\n')
  assert.doesNotMatch(pageImports, /PetSurface|usePetRuntime|bridge|engine\//, '页面不得 import 覆盖层与物理引擎')
  assert.match(page, /createBlockyRig/, '页面直接搭方块人骨架')
  assert.match(page, /blockyPose/, '页面直接按动作计算姿态')
  assert.match(page, /skinCanvasFromBytes/, '页面支持加载 64×64 自定义皮肤')
  assert.match(page, /type="file"/, '皮肤加载入口必须存在')
})

test('底部动作组覆盖移动/表演/互动三组', () => {
  const page = readFileSync(new URL('../../../core/ui/src/pet/ui/PetAnimLab.vue', import.meta.url), 'utf8')
  for (const group of ['移动', '表演', '互动']) {
    assert.match(page, new RegExp(`name: '${group}'`), `必须有「${group}」动作组`)
  }
  for (const action of ['idle', 'walk', 'jump', 'fall', 'land', 'climb', 'hang', 'jump_happy', 'dance', 'rest', 'interact', 'interact_head']) {
    assert.match(page, new RegExp(`id: '${action}'`), `动作组必须包含 ${action}`)
  }
})
