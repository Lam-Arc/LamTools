/**
 * 方块人骨架构建（依赖 Three.js，但由调用方注入，便于与渲染层共享同一个实例）。
 *
 * 结构：脚底在 y=0，总高 32 个模型单位，之后统一缩放到宠物框高度。
 * 每个肢体是一个 Group，盒子几何向下偏移半个高度，这样旋转轴落在肩/髋上。
 */
import type * as THREE_NS from 'three'
import {
  blockyPose,
  boxFaceUvs,
  skinBoxes,
  type BlockyModel,
  type BlockyPose,
  type SkinBox,
} from './blocky.ts'

export interface BlockyRig {
  root: import('three').Group
  applyPose(pose: BlockyPose): void
  setSkin(texture: import('three').Texture): void
  dispose(): void
}

interface RigParts {
  head: import('three').Group
  torso: import('three').Mesh
  armLeft: import('three').Group
  armRight: import('three').Group
  legLeft: import('three').Group
  legRight: import('three').Group
  materials: import('three').MeshStandardMaterial[]
  geometries: import('three').BufferGeometry[]
}

function applyBoxUvs(
  THREE: typeof THREE_NS,
  geometry: import('three').BufferGeometry,
  box: SkinBox,
  textureWidth: number,
  textureHeight: number,
): void {
  const faces = boxFaceUvs(box, textureWidth, textureHeight)
  const uv = geometry.getAttribute('uv') as import('three').BufferAttribute
  // BoxGeometry 每个面 4 个顶点，顺序与 faces.order 一致。
  for (let faceIndex = 0; faceIndex < faces.rects.length; faceIndex += 1) {
    const rect = faces.rects[faceIndex]
    const base = faceIndex * 4
    // 顶点顺序：左上、右上、左下、右下（three 的 BoxGeometry 约定）。
    uv.setXY(base + 0, rect.u0, rect.v1)
    uv.setXY(base + 1, rect.u1, rect.v1)
    uv.setXY(base + 2, rect.u0, rect.v0)
    uv.setXY(base + 3, rect.u1, rect.v0)
  }
  uv.needsUpdate = true
}

export function createBlockyRig(
  THREE: typeof THREE_NS,
  options: { model: BlockyModel; texture: import('three').Texture; textureWidth: number; textureHeight: number },
): BlockyRig {
  const boxes = skinBoxes(options.model)
  const materials: import('three').MeshStandardMaterial[] = []
  const geometries: import('three').BufferGeometry[] = []

  const makeBox = (box: SkinBox, pivotOffsetY = 0): import('three').Mesh => {
    const geometry = new THREE.BoxGeometry(box.w, box.h, box.d)
    geometries.push(geometry)
    applyBoxUvs(THREE, geometry, box, options.textureWidth, options.textureHeight)
    const material = new THREE.MeshStandardMaterial({
      map: options.texture,
      roughness: 0.85,
      metalness: 0.02,
      // 皮肤里可能有透明像素，开启 alpha 测试避免出现黑色方块。
      transparent: true,
      alphaTest: 0.35,
    })
    materials.push(material)
    const mesh = new THREE.Mesh(geometry, material)
    mesh.position.y = pivotOffsetY
    return mesh
  }

  const root = new THREE.Group()
  const torso = makeBox(boxes.body)
  torso.position.y = 18
  root.add(torso)

  const head = new THREE.Group()
  head.position.y = 24
  const headMesh = makeBox(boxes.head)
  headMesh.position.y = 4
  head.add(headMesh)
  root.add(head)

  const armWidth = options.model === 'alex' ? 3 : 4
  const shoulderX = 4 + armWidth / 2
  const makeArm = (sign: number, box: SkinBox) => {
    const group = new THREE.Group()
    // 肩膀略低于躯干顶部，动作看起来才像真人抬臂。
    group.position.set(sign * shoulderX, 22, 0)
    const mesh = makeBox(box, -6)
    group.add(mesh)
    root.add(group)
    return group
  }
  const armRight = makeArm(-1, boxes.armRight)
  const armLeft = makeArm(1, boxes.armLeft)

  const makeLeg = (sign: number, box: SkinBox) => {
    const group = new THREE.Group()
    group.position.set(sign * 2, 12, 0)
    const mesh = makeBox(box, -6)
    group.add(mesh)
    root.add(group)
    return group
  }
  const legRight = makeLeg(-1, boxes.legRight)
  const legLeft = makeLeg(1, boxes.legLeft)

  const parts: RigParts = { head, torso, armLeft, armRight, legLeft, legRight, materials, geometries }

  return {
    root,
    applyPose(pose: BlockyPose) {
      parts.head.rotation.set(pose.head.x, pose.head.y, pose.head.z)
      parts.torso.rotation.set(pose.body.x, pose.body.y, pose.body.z)
      parts.armLeft.rotation.set(pose.armLeft.x, pose.armLeft.y, pose.armLeft.z)
      parts.armRight.rotation.set(pose.armRight.x, pose.armRight.y, pose.armRight.z)
      parts.legLeft.rotation.set(pose.legLeft.x, pose.legLeft.y, pose.legLeft.z)
      parts.legRight.rotation.set(pose.legRight.x, pose.legRight.y, pose.legRight.z)
      // bob 用模型单位，脚底贴地的偏移在世界缩放下自动成立。
      parts.head.position.y = 24 + pose.bob
      parts.torso.position.y = 18 + pose.bob
      parts.armLeft.position.y = 22 + pose.bob
      parts.armRight.position.y = 22 + pose.bob
    },
    setSkin(texture: import('three').Texture) {
      for (const material of parts.materials) {
        material.map = texture
        material.needsUpdate = true
      }
    },
    dispose() {
      for (const geometry of geometries) geometry.dispose()
      for (const material of materials) material.dispose()
      // 纹理由渲染层统一持有，这里不销毁，避免换肤后旧纹理被重复释放。
    },
  }
}

/** 供渲染层直接使用的默认姿态，避免外部重复计算。 */
export function neutralBlockyPose(): BlockyPose {
  return blockyPose('idle', 0)
}
