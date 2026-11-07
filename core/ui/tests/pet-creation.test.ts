/**
 * 零代码桌宠创建：图片 → 动作映射 → 角色包条目。
 *
 * user:“普通用户无需写 JSON/准备压缩包，即能用一张图片创建可运行桌宠；
 * 上传多张图即可定义动作”+“自动生成 pet.json；对用户完全隐藏”
 */
import { describe, expect, it } from 'vitest'
import { buildPetCreationPlan, type CreationFile } from '@/pet/creation.ts'

function image(name: string, width = 128, height = 160): CreationFile {
  return {
    name,
    size: 16,
    bytes: new Uint8Array([1, 2, 3, 4]),
    width,
    height,
  }
}

describe('从图片创建桌宠', () => {
  it('一张图片直接生成 idle，并自动写 pet.json', () => {
    const plan = buildPetCreationPlan({ name: '鲸鱼娘', files: [image('whale.png', 200, 320)] })
    expect(plan.errors).toEqual([])
    expect(plan.name).toBe('鲸鱼娘')
    expect(plan.actions.idle).toEqual({ type: 'static', source: 'whale.png' })
    expect(plan.spriteWidth).toBe(200)
    expect(plan.spriteHeight).toBe(320)
    expect(plan.entries.some(entry => entry.rel === 'pet.json')).toBe(true)
    const manifest = JSON.parse(new TextDecoder().decode(plan.entries.find(entry => entry.rel === 'pet.json')!.bytes))
    expect(manifest.schema_version).toBe(1)
    expect(manifest.actions.idle.source).toBe('whale.png')
    expect(manifest.hitboxes.length).toBeGreaterThan(0)
  })

  it('同一前缀的多张图自动组成序列帧', () => {
    const plan = buildPetCreationPlan({
      name: '走路',
      files: [image('walk_0.png'), image('walk_1.png'), image('walk_2.png')],
    })
    expect(plan.errors).toEqual([])
    expect(plan.actions.walk).toMatchObject({
      type: 'frames',
      sources: ['walk_0.png', 'walk_1.png', 'walk_2.png'],
    })
    // 没有独立 idle 时用第一张图作为待机，绝不会创建空角色。
    expect(plan.actions.idle).toBeTruthy()
  })

  it('单张 walk/jump 按文件名映射为静态动作', () => {
    const plan = buildPetCreationPlan({
      name: '动作包',
      files: [image('walk.png'), image('jump.png')],
    })
    expect(plan.actions.walk).toEqual({ type: 'static', source: 'walk.png' })
    expect(plan.actions.jump).toEqual({ type: 'static', source: 'jump.png' })
    expect(plan.actions.idle).toBeTruthy()
  })

  it('同名图片自动改名，避免互相覆盖', () => {
    const plan = buildPetCreationPlan({
      name: '重复',
      files: [image('same.png'), image('same.png')],
    })
    const rels = plan.entries.filter(entry => entry.rel !== 'pet.json').map(entry => entry.rel)
    expect(new Set(rels.map(rel => rel.toLowerCase())).size).toBe(2)
  })

  it('不支持的格式会跳过；全部不可用时给出错误', () => {
    const plan = buildPetCreationPlan({
      name: '坏文件',
      files: [{ name: 'run.js', size: 4, bytes: new Uint8Array([1]), width: 1, height: 1 }],
    })
    expect(plan.entries).toEqual([])
    expect(plan.errors.length).toBeGreaterThan(0)
    expect(plan.warnings.some(item => item.includes('不支持'))).toBe(true)
  })

  it('超大图片和超限尺寸在写入前拒绝', () => {
    const tooWide = buildPetCreationPlan({ name: '大图', files: [image('huge.png', 9000, 9000)] })
    expect(tooWide.errors.some(error => error.includes('9000'))).toBe(true)
  })
})
