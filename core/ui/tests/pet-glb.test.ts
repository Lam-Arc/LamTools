/**
 * 自制骨骼 GLB 的结构验收。
 *
 * 这里不是"文件存在就算过"：解析二进制容器、校验 accessor 与实际字节长度一致、
 * 蒙皮权重和为 1、动画通道指向真实节点，再走一遍导入器确认能被识别成模型动作。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { analyzeImport, type ImportScanResult } from '@/pet/assets/importer.ts'

const STICKMAN_DIR = resolve(process.cwd(), '..', '..', 'core', 'examples', 'sunday-pet', 'stickman')

interface GlbFile {
  json: Record<string, unknown>
  bin: Uint8Array
}

function readGlb(path: string): GlbFile {
  const file = new Uint8Array(readFileSync(path))
  const view = new DataView(file.buffer, file.byteOffset, file.byteLength)
  expect(view.getUint32(0, true)).toBe(0x46546c67) // glTF
  expect(view.getUint32(4, true)).toBe(2)
  expect(view.getUint32(8, true)).toBe(file.byteLength)
  const jsonLength = view.getUint32(12, true)
  expect(view.getUint32(16, true)).toBe(0x4e4f534a) // JSON
  const jsonText = new TextDecoder().decode(file.subarray(20, 20 + jsonLength))
  const json = JSON.parse(jsonText) as Record<string, unknown>
  const binHeaderAt = 20 + jsonLength
  const binLength = view.getUint32(binHeaderAt, true)
  expect(view.getUint32(binHeaderAt + 4, true)).toBe(0x004e4942) // BIN
  const bin = file.subarray(binHeaderAt + 8, binHeaderAt + 8 + binLength)
  return { json, bin }
}

const COMPONENT_SIZE: Record<number, number> = { 5121: 1, 5123: 2, 5125: 4, 5126: 4 }
const TYPE_SIZE: Record<string, number> = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 }

describe('骨骼火柴人 GLB', () => {
  const file = readGlb(resolve(STICKMAN_DIR, 'stickman.glb'))
  const json = file.json as {
    skins: { joints: number[]; inverseBindMatrices: number }[]
    nodes: { name?: string; children?: number[] }[]
    meshes: { primitives: { attributes: Record<string, number>; indices: number }[] }[]
    animations: { name: string; channels: { target: { node: number; path: string } }[] }[]
    accessors: { bufferView: number; componentType: number; count: number; type: string }[]
    bufferViews: { byteOffset: number; byteLength: number }[]
    buffers: { byteLength: number }[]
  }

  it('容器是合法 glTF 2.0 二进制', () => {
    expect(json.skins.length).toBe(1)
    expect(json.buffers[0].byteLength).toBe(file.bin.byteLength)
  })

  it('骨架有三根骨骼并带逆绑定矩阵', () => {
    const skin = json.skins[0]
    expect(skin.joints.length).toBe(3)
    const accessor = json.accessors[skin.inverseBindMatrices]
    expect(accessor.type).toBe('MAT4')
    expect(accessor.count).toBe(3)
  })

  it('节点层级是 Armature → Hip → Spine → Head', () => {
    const names = json.nodes.map(node => node.name)
    expect(names.slice(0, 4)).toEqual(['Armature', 'Hip', 'Spine', 'Head'])
    expect(json.nodes[0].children).toEqual([1])
    expect(json.nodes[1].children).toEqual([2])
    expect(json.nodes[2].children).toEqual([3])
  })

  it('网格带蒙皮属性（JOINTS_0 / WEIGHTS_0）', () => {
    const primitive = json.meshes[0].primitives[0]
    expect(primitive.attributes.JOINTS_0).toBeTypeOf('number')
    expect(primitive.attributes.WEIGHTS_0).toBeTypeOf('number')
    expect(primitive.attributes.POSITION).toBeTypeOf('number')
  })

  it('每个 accessor 的实际字节都在对应 bufferView 内', () => {
    for (const accessor of json.accessors) {
      const view = json.bufferViews[accessor.bufferView]
      const needed = accessor.count * (TYPE_SIZE[accessor.type] || 1) * (COMPONENT_SIZE[accessor.componentType] || 1)
      expect(view.byteLength).toBeGreaterThanOrEqual(needed)
      expect(view.byteOffset + view.byteLength).toBeLessThanOrEqual(file.bin.byteLength)
    }
  })

  it('蒙皮权重每顶点归一（和 = 1）', () => {
    const primitive = json.meshes[0].primitives[0]
    const accessor = json.accessors[primitive.attributes.WEIGHTS_0]
    const view = json.bufferViews[accessor.bufferView]
    const data = new Float32Array(
      file.bin.buffer,
      file.bin.byteOffset + view.byteOffset,
      accessor.count * 4,
    )
    for (let vertex = 0; vertex < accessor.count; vertex += 1) {
      const sum = data[vertex * 4] + data[vertex * 4 + 1] + data[vertex * 4 + 2] + data[vertex * 4 + 3]
      expect(sum).toBeCloseTo(1, 5)
    }
  })

  it('四段动画都存在且通道指向真实节点', () => {
    const names = json.animations.map(animation => animation.name)
    expect(names).toEqual(expect.arrayContaining(['Idle', 'Walk', 'Jump', 'Dance']))
    for (const animation of json.animations) {
      expect(animation.channels.length).toBeGreaterThan(0)
      for (const channel of animation.channels) {
        expect(json.nodes[channel.target.node]).toBeDefined()
        expect(channel.target.path).toBe('rotation')
      }
    }
  })
})

describe('骨骼角色的导入识别', () => {
  it('pet.json + GLB 被识别为可播放模型动作', () => {
    const manifest = readFileSync(resolve(STICKMAN_DIR, 'pet.json'), 'utf8')
    const scan: ImportScanResult = {
      root: STICKMAN_DIR,
      files: [
        { rel: 'pet.json', size: manifest.length, ext: 'json' },
        { rel: 'stickman.glb', size: 9484, ext: 'glb' },
      ],
      totalBytes: manifest.length + 9484,
    }
    const analysis = analyzeImport(scan, manifest)
    expect(analysis.ok).toBe(true)
    expect(analysis.unsupported).toEqual([])
    const walk = analysis.actions.walk
    expect(walk?.type).toBe('model')
    if (walk?.type === 'model') {
      expect(walk.source).toBe('stickman.glb')
      expect(walk.clip).toBe('Walk')
      expect(walk.loop).toBe(true)
    }
    const jump = analysis.actions.jump
    if (jump?.type === 'model') {
      expect(jump.clip).toBe('Jump')
      expect(jump.loop).toBe(false)
    }
    // 如果忘了 idle，会自动补一个基础姿态；这里显式配了 idle，应该原样保留。
    expect(analysis.actions.idle?.type).toBe('model')
  })
})
