#!/usr/bin/env node
/**
 * 生成一只"骨骼火柴人"测试角色（GLB）。
 *
 * 为什么用脚本而不是 Blender：这套动画只需要三段刚性骨骼，脚本能保证
 * 每次产出一模一样的文件，方便回归；也避免把体积巨大的 DCC 工具带进构建。
 * 需要真实带蒙皮权重的复杂资产时，再引入 Blender 也不冲突。
 *
 * 产出：core/examples/sunday-pet/stickman/stickman.glb + pet.json
 *
 * 用法：node scripts/make-stickman.mjs
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outputDir = join(here, '..', '..', '..', 'core', 'examples', 'sunday-pet', 'stickman')

/** 三段躯干：每段一个盒子，刚性绑定到一根骨骼。 */
const SEGMENTS = 3
const SEGMENT_HEIGHT = 0.4
const SEGMENT_HALF_WIDTH = 0.09

function quatAxisAngle(axis, angle) {
  const half = angle / 2
  const s = Math.sin(half)
  return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(half)]
}

/** 生成一个盒子的 24 顶点（每面 4 个，带法线）与 36 个索引。 */
function buildSegmentVertices(yBase) {
  const positions = []
  const normals = []
  const indices = []
  const faces = [
    { normal: [1, 0, 0], corners: [[1, 0, -1], [1, 0, 1], [1, 1, 1], [1, 1, -1]] },
    { normal: [-1, 0, 0], corners: [[-1, 0, 1], [-1, 0, -1], [-1, 1, -1], [-1, 1, 1]] },
    { normal: [0, 1, 0], corners: [[-1, 1, 1], [1, 1, 1], [1, 1, -1], [-1, 1, -1]] },
    { normal: [0, -1, 0], corners: [[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]] },
    { normal: [0, 0, 1], corners: [[-1, 0, 1], [1, 0, 1], [1, 1, 1], [-1, 1, 1]] },
    { normal: [0, 0, -1], corners: [[1, 0, -1], [-1, 0, -1], [-1, 1, -1], [1, 1, -1]] },
  ]
  let vertexBase = 0
  for (const face of faces) {
    for (const corner of face.corners) {
      positions.push(
        corner[0] * SEGMENT_HALF_WIDTH,
        yBase + corner[1] * SEGMENT_HEIGHT,
        corner[2] * SEGMENT_HALF_WIDTH,
      )
      normals.push(...face.normal)
    }
    indices.push(
      vertexBase, vertexBase + 1, vertexBase + 2,
      vertexBase, vertexBase + 2, vertexBase + 3,
    )
    vertexBase += 4
  }
  return { positions, normals, indices }
}

function buildMesh() {
  const positions = []
  const normals = []
  const indices = []
  const joints = []
  const weights = []
  for (let segment = 0; segment < SEGMENTS; segment += 1) {
    const base = segment * SEGMENT_HEIGHT
    const built = buildSegmentVertices(base)
    const vertexOffset = positions.length / 3
    positions.push(...built.positions)
    normals.push(...built.normals)
    indices.push(...built.indices.map(index => index + vertexOffset))
    const vertexCount = built.positions.length / 3
    for (let vertex = 0; vertex < vertexCount; vertex += 1) {
      // 刚性蒙皮：每个顶点只受一根骨骼影响，权重恒为 1。
      joints.push(segment, 0, 0, 0)
      weights.push(1, 0, 0, 0)
    }
  }
  return { positions, normals, indices, joints, weights, vertexCount: positions.length / 3 }
}

function buildAnimations() {
  const times = [0, 0.5, 1, 1.5]
  const makeRotation = (axis, amplitude, phase = 0) =>
    times.flatMap(time => quatAxisAngle(axis, Math.sin(time * Math.PI * 2 + phase) * amplitude))
  return [
    {
      name: 'Idle',
      // 轻微摆头 + 身体呼吸
      tracks: [
        { node: 2, path: 'rotation', values: makeRotation([1, 0, 0], 0.05) },
        { node: 3, path: 'rotation', values: makeRotation([1, 0, 0], 0.08) },
      ],
    },
    {
      name: 'Walk',
      tracks: [
        { node: 1, path: 'rotation', values: makeRotation([1, 0, 0], 0.25) },
        { node: 2, path: 'rotation', values: makeRotation([1, 0, 0], 0.22, Math.PI) },
      ],
    },
    {
      name: 'Jump',
      tracks: [
        { node: 1, path: 'rotation', values: makeRotation([1, 0, 0], 0.35) },
        { node: 3, path: 'rotation', values: makeRotation([1, 0, 0], 0.2) },
      ],
    },
    {
      name: 'Dance',
      tracks: [
        { node: 1, path: 'rotation', values: makeRotation([0, 0, 1], 0.4) },
        { node: 2, path: 'rotation', values: makeRotation([1, 0, 0], 0.3) },
        { node: 3, path: 'rotation', values: makeRotation([0, 1, 0], 0.5) },
      ],
    },
  ]
}

function float32(values) {
  return Buffer.from(new Float32Array(values).buffer)
}

function uint16(values) {
  return Buffer.from(new Uint16Array(values).buffer)
}

function align4(buffer) {
  const remainder = buffer.length % 4
  return remainder === 0 ? buffer : Buffer.concat([buffer, Buffer.alloc(4 - remainder)])
}

function main() {
  const mesh = buildMesh()
  const animations = buildAnimations()

  const chunks = []
  const bufferViews = []
  const accessors = []
  const addView = (buffer, target) => {
    const offset = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
    chunks.push(align4(buffer))
    bufferViews.push({
      buffer: 0,
      byteOffset: offset,
      byteLength: buffer.length,
      ...(target ? { target } : {}),
    })
    return bufferViews.length - 1
  }
  const addAccessor = (view, componentType, count, type, extra = {}) => {
    accessors.push({ bufferView: view, componentType, count, type, ...extra })
    return accessors.length - 1
  }

  const positionView = addView(float32(mesh.positions), 34962)
  const normalView = addView(float32(mesh.normals), 34962)
  const jointView = addView(uint16(mesh.joints), 34962)
  const weightView = addView(float32(mesh.weights), 34962)
  const indexView = addView(uint16(mesh.indices), 34963)

  const bounds = { min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] }
  for (let index = 0; index < mesh.positions.length; index += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      bounds.min[axis] = Math.min(bounds.min[axis], mesh.positions[index + axis])
      bounds.max[axis] = Math.max(bounds.max[axis], mesh.positions[index + axis])
    }
  }

  const positionAccessor = addAccessor(positionView, 5126, mesh.vertexCount, 'VEC3', bounds)
  const normalAccessor = addAccessor(normalView, 5126, mesh.vertexCount, 'VEC3')
  const jointAccessor = addAccessor(jointView, 5123, mesh.vertexCount, 'VEC4')
  const weightAccessor = addAccessor(weightView, 5126, mesh.vertexCount, 'VEC4')
  const indexAccessor = addAccessor(indexView, 5123, mesh.indices.length, 'SCALAR')

  // 逆绑定矩阵：每根骨骼在静止姿态下的平移取反。
  const inverseBind = []
  for (let joint = 0; joint < SEGMENTS; joint += 1) {
    inverseBind.push(
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      0, -joint * SEGMENT_HEIGHT, 0, 1,
    )
  }
  const inverseBindView = addView(float32(inverseBind))
  const inverseBindAccessor = addAccessor(inverseBindView, 5126, SEGMENTS, 'MAT4')

  const animationEntries = animations.map(animation => {
    const samplers = []
    const channels = []
    for (const track of animation.tracks) {
      const timeView = addView(float32([0, 0.5, 1, 1.5]))
      const timeAccessor = addAccessor(timeView, 5126, 4, 'SCALAR', { min: [0], max: [1.5] })
      const valueAccessor = addAccessor(addView(float32(track.values)), 5126, track.values.length / 4, 'VEC4')
      samplers.push({ input: timeAccessor, output: valueAccessor, interpolation: 'LINEAR' })
      channels.push({ sampler: samplers.length - 1, target: { node: track.node, path: track.path } })
    }
    return { name: animation.name, samplers, channels }
  })

  const bin = Buffer.concat(chunks)
  const gltf = {
    asset: { version: '2.0', generator: 'sunday-pet stickman generator' },
    scene: 0,
    scenes: [{ nodes: [0, 4] }],
    nodes: [
      { name: 'Armature', children: [1] },
      { name: 'Hip', translation: [0, 0, 0], children: [2] },
      { name: 'Spine', translation: [0, SEGMENT_HEIGHT, 0], children: [3] },
      { name: 'Head', translation: [0, SEGMENT_HEIGHT, 0] },
      { name: 'Body', mesh: 0, skin: 0 },
    ],
    skins: [{ name: 'Rig', joints: [1, 2, 3], inverseBindMatrices: inverseBindAccessor, skeleton: 1 }],
    meshes: [{
      name: 'StickmanMesh',
      primitives: [{
        attributes: {
          POSITION: positionAccessor,
          NORMAL: normalAccessor,
          JOINTS_0: jointAccessor,
          WEIGHTS_0: weightAccessor,
        },
        indices: indexAccessor,
        material: 0,
      }],
    }],
    materials: [{
      name: 'StickmanSkin',
      pbrMetallicRoughness: {
        baseColorFactor: [0.55, 0.72, 0.95, 1],
        metallicFactor: 0.05,
        roughnessFactor: 0.7,
      },
      doubleSided: false,
    }],
    animations: animationEntries,
    bufferViews,
    accessors,
    buffers: [{ byteLength: bin.length }],
  }

  const json = align4(Buffer.from(JSON.stringify(gltf), 'utf8'))
  const header = Buffer.alloc(12)
  header.writeUInt32LE(0x46546c67, 0) // "glTF"
  header.writeUInt32LE(2, 4)
  header.writeUInt32LE(12 + 8 + json.length + 8 + bin.length, 8)
  const jsonHeader = Buffer.alloc(8)
  jsonHeader.writeUInt32LE(json.length, 0)
  jsonHeader.writeUInt32LE(0x4e4f534a, 4) // "JSON"
  const binHeader = Buffer.alloc(8)
  binHeader.writeUInt32LE(bin.length, 0)
  binHeader.writeUInt32LE(0x004e4942, 4) // "BIN"
  const glb = Buffer.concat([header, jsonHeader, json, binHeader, bin])

  mkdirSync(outputDir, { recursive: true })
  writeFileSync(join(outputDir, 'stickman.glb'), glb)

  const manifest = {
    schema_version: 1,
    name: 'Sunday Stickman',
    scale: 1,
    actions: {
      idle: { source: 'stickman.glb', type: 'model', model_clip: 'Idle', loop: true },
      walk: { source: 'stickman.glb', type: 'model', model_clip: 'Walk', loop: true },
      jump: { source: 'stickman.glb', type: 'model', model_clip: 'Jump', loop: false },
      dance: { source: 'stickman.glb', type: 'model', model_clip: 'Dance', loop: true },
    },
    physics: { radius: 26 },
  }
  writeFileSync(join(outputDir, 'pet.json'), `${JSON.stringify(manifest, null, 2)}\n`)
  console.log(`stickman.glb ${glb.length} bytes, ${mesh.vertexCount} vertices, ${animations.length} animations`)
}

main()
