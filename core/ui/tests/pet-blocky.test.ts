/**
 * 方块人预设的纯逻辑测试：皮肤网格、盒面 UV、动作姿态。
 *
 * UV 错位会让角色"前后脸对调"，姿态错会让走路顺拐，这两类问题在真机上
 * 很难定位，所以先在这里钉死。
 */
import { describe, expect, it } from 'vitest'
import { blockyPose, boxFaceUvs, defaultSkinPaint, skinBoxes } from '@/pet/render/blocky.ts'
import { clipPrimarySource, frameAt } from '@/pet/engine/sprite.ts'
import { rendererFor, modelTargetBox } from '@/pet/render/types.ts'

describe('皮肤网格', () => {
  it('Steve 的手臂 4 宽，Alex 的 3 宽，其余部位一致', () => {
    const steve = skinBoxes('steve')
    const alex = skinBoxes('alex')
    expect(steve.armRight.w).toBe(4)
    expect(alex.armRight.w).toBe(3)
    expect(steve.head).toEqual(alex.head)
    expect(steve.body).toEqual(alex.body)
    expect(steve.legRight).toEqual(alex.legRight)
  })

  it('头和身体落在标准网格位置', () => {
    const boxes = skinBoxes('steve')
    expect(boxes.head).toEqual({ x: 0, y: 0, w: 8, h: 8, d: 8 })
    expect(boxes.body).toEqual({ x: 16, y: 16, w: 8, h: 12, d: 4 })
    expect(boxes.legRight).toEqual({ x: 0, y: 16, w: 4, h: 12, d: 4 })
    expect(boxes.legLeft).toEqual({ x: 16, y: 48, w: 4, h: 12, d: 4 })
  })

  it('内置皮肤覆盖所有部位，且颜色可区分', () => {
    const paint = defaultSkinPaint('steve')
    expect(paint.length).toBe(6)
    const colors = new Set(paint.map(part => part.face))
    expect(colors.size).toBeGreaterThan(1)
  })
})

describe('盒面 UV', () => {
  it('六个面按 BoxGeometry 的顺序返回，主面朝向正确', () => {
    const head = boxFaceUvs(skinBoxes('steve').head, 64, 64)
    expect(head.order).toEqual(['right', 'left', 'top', 'bottom', 'front', 'back'])
    expect(head.rects.length).toBe(6)
  })

  it('头部的正脸取 (8,8) 的 8×8 区域，并做了 V 轴翻转', () => {
    const head = boxFaceUvs(skinBoxes('steve').head, 64, 64)
    const front = head.rects[4]
    expect(front.u0).toBeCloseTo(8 / 64, 6)
    expect(front.u1).toBeCloseTo(16 / 64, 6)
    // 画布 y=8..16 → UV v=1-16/64 .. 1-8/64
    expect(front.v0).toBeCloseTo(1 - 16 / 64, 6)
    expect(front.v1).toBeCloseTo(1 - 8 / 64, 6)
  })

  it('+X 是角色左侧、-X 是角色右侧（侧脸与皮肤左右不镜像）', () => {
    // user:"你没有发现你的面向方向左右搞反了吗"+
    // (骨架把左臂放在 +X、右臂放在 -X；展开图的左右必须对应到 -X/+X。)
    const head = boxFaceUvs(skinBoxes('steve').head, 64, 64)
    expect(head.rects[0].u0).toBeCloseTo(16 / 64, 6) // +X 取皮肤左脸
    expect(head.rects[1].u0).toBeCloseTo(0 / 64, 6) // -X 取皮肤右脸
  })

  it('顶部与底部横向排在头顶侧，且互不重叠', () => {
    const head = boxFaceUvs(skinBoxes('steve').head, 64, 64)
    const top = head.rects[2]
    const bottom = head.rects[3]
    expect(top.u0).toBeCloseTo(8 / 64, 6)
    expect(bottom.u0).toBeCloseTo(16 / 64, 6)
    expect(bottom.u0).toBeGreaterThan(top.u0)
  })

  it('所有 UV 都落在 0..1 之内', () => {
    for (const box of Object.values(skinBoxes('steve'))) {
      for (const rect of boxFaceUvs(box, 64, 64).rects) {
        expect(rect.u0).toBeGreaterThanOrEqual(0)
        expect(rect.u1).toBeLessThanOrEqual(1)
        expect(rect.v0).toBeGreaterThanOrEqual(0)
        expect(rect.v1).toBeLessThanOrEqual(1)
      }
    }
  })
})

describe('动作姿态', () => {
  it('走路时四肢交替摆动，不会顺拐', () => {
    const pose = blockyPose('walk', 120)
    expect(Math.sign(pose.armLeft.x)).toBe(-Math.sign(pose.armRight.x))
    expect(Math.sign(pose.legLeft.x)).toBe(-Math.sign(pose.legRight.x))
    expect(pose.armLeft.x).not.toBe(0)
  })

  it('跳跃双臂上举，下落双臂外张', () => {
    const jump = blockyPose('jump', 60)
    expect(jump.armLeft.x).toBeLessThan(-1.5)
    expect(jump.armRight.x).toBeLessThan(-1.5)
    const fall = blockyPose('fall', 60)
    expect(fall.armLeft.z).not.toBe(0)
  })

  it('休息是坐姿：腿向前伸且外分，身体坐到低处（腿不能被身体挡住）', () => {
    // user:"而且休息的时候为什么没有腿"+(绕 +X 转是往后折，正面看不见；改向前。)
    const rest = blockyPose('rest', 0)
    expect(rest.legLeft.x).toBeLessThan(-1)
    expect(rest.legRight.x).toBeLessThan(-1)
    expect(rest.legLeft.z).toBeGreaterThan(0)
    expect(rest.legRight.z).toBeLessThan(0)
    expect(rest.bob).toBeLessThan(-4)
  })

  it('攀爬与悬挂把手抬到头顶以上', () => {
    expect(blockyPose('climb', 100).armLeft.x).toBeGreaterThan(2)
    expect(blockyPose('hang', 0).armRight.x).toBeGreaterThan(3)
  })

  it('所有动作的姿态都是有限数值', () => {
    for (const actionId of ['idle', 'walk', 'jump', 'jump_happy', 'fall', 'climb', 'hang', 'rest', 'dance', 'interact']) {
      const pose = blockyPose(actionId, 250)
      for (const joint of [pose.head, pose.body, pose.armLeft, pose.armRight, pose.legLeft, pose.legRight]) {
        expect(Number.isFinite(joint.x)).toBe(true)
        expect(Number.isFinite(joint.y)).toBe(true)
        expect(Number.isFinite(joint.z)).toBe(true)
      }
      expect(Number.isFinite(pose.bob)).toBe(true)
    }
  })

  it('走路周期固定，不随移动速度倍速', () => {
    // user:"同时不要给走路动画开倍速，我从来没有说过有这一项吧"
    const a = blockyPose('walk', 100)
    const b = blockyPose('walk', 100)
    expect(a.legLeft.x).toBeCloseTo(b.legLeft.x, 10)
    // 固定 2Hz：过了半个周期（250ms），摆动方向相反。
    const later = blockyPose('walk', 350)
    expect(Math.sign(later.legLeft.x)).toBe(-Math.sign(a.legLeft.x) || Math.sign(later.legLeft.x))
    expect(Math.abs(later.legLeft.x - a.legLeft.x)).toBeGreaterThan(1e-3)
  })
})

describe('方块人接入渲染层', () => {
  it('方块人交给 Three 层，帧不带裁剪', () => {
    expect(rendererFor({ type: 'blocky' })).toBe('three')
    const frame = frameAt({ type: 'blocky', skin: 'skins/a.png' }, 0, { width: 92, height: 158 })
    expect(frame.type).toBe('blocky')
    expect(frame.source).toBe('skins/a.png')
  })

  it('没有皮肤时用内置皮肤，主资源为空字符串', () => {
    expect(clipPrimarySource({ type: 'blocky' })).toBe('')
    expect(clipPrimarySource({ type: 'blocky', skin: 'skins/b.png' })).toBe('skins/b.png')
  })

  it('模型框沿用精灵框，不吃 model_scale', () => {
    const rect = { x: 10, y: 20, width: 90, height: 150 }
    expect(modelTargetBox(rect, { type: 'blocky' })).toEqual(rect)
  })
})
