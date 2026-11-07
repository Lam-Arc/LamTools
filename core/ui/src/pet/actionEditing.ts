/**
 * 动作编辑的纯规则。
 *
 * user:“可自由增加‘挥手’等自定义表现动作”+
 * “表现动作可绑定点击/双击指定身体 Hitbox”+
 * (动作 ID 稳定、单图=静态、多图=序列帧；被命中区引用的动作不能静默删除。)
 */
import type { PetHitbox, PetClip } from './engine/sprite.ts'

export function slugActionName(text: string): string {
  const value = text.trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-').replace(/^-+|-+$/g, '')
  return value || 'action'
}

export function uniqueActionId(used: string[], base: string): string {
  const existing = new Set(used)
  let id = base
  for (let index = 2; existing.has(id); index += 1) id = `${base}-${index}`
  return id
}

/** 单张图片是静态动作；多张按选择顺序组成序列帧。 */
export function clipForSources(sources: string[], fps = 12): PetClip {
  return sources.length === 1
    ? { type: 'static', source: sources[0] }
    : { type: 'frames', sources: [...sources], fps, loop: true }
}

/** 返回 null 表示可删除；否则返回给用户看的原因。 */
export function actionRemovalError(
  actionId: string,
  actions: Record<string, unknown>,
  hitboxes: PetHitbox[],
): string | null {
  if (actionId === 'idle') return '待机动作不能删除；请先绑定另一张图片作为待机'
  if (!(actionId in actions)) return '动作不存在'
  const referenced = hitboxes.some(hitbox => hitbox.action === actionId || hitbox.doubleAction === actionId)
  if (referenced) return `「${actionId}」仍被命中区引用，请先修改命中区的点击/双击动作`
  return null
}
