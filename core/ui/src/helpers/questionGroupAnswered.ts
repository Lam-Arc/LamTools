/**
 * 「这个问组已经被回答过」的记录。
 *
 * user:“我这一张卡明明回答了，我看见它折叠了，随后又出现在我的回答下方，且变成了未回答，
 * 但是根据模型的回复它确实收到了我的回答”+(已回答此前只存在组件本地态里：卡片一旦因为
 * 位置换算、重复投影或重新打开会话而重新挂载，就退回未回答——模型其实早就收到了。
 * 这里按问组 id 记住答案，重新挂上来时据此回到「已回答」。)
 *
 * 为什么要落到 localStorage：后端投影把提问行发成 `status: "waiting"`，payload 里只有
 * 题目，没有答案也没有关闭标记，所以"答过了"这件事在数据里读不到。记在本机可以扛过
 * 刷新与重开应用；真正的真相仍在会话库里，等投影补上 `closed_reason` / `answers` 之后，
 * 这里会自动退化成缓存。
 */
const STORAGE_KEY = 'lamtools.question-groups.answered'
const MAX_ENTRIES = 200

type AnswerMap = Record<string, string>
const answeredGroups = new Map<string, AnswerMap>()
let hydrated = false

function storage(): Storage | null {
  try {
    return typeof window !== 'undefined' && window.localStorage ? window.localStorage : null
  } catch {
    return null
  }
}

function hydrate(): void {
  if (hydrated) return
  hydrated = true
  const store = storage()
  if (!store) return
  try {
    const raw = store.getItem(STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw) as Record<string, AnswerMap>
    for (const [groupId, answers] of Object.entries(parsed || {})) {
      if (groupId && answers && typeof answers === 'object') answeredGroups.set(groupId, answers)
    }
  } catch {
    // 坏数据只影响这一次回填，不影响卡片本身。
  }
}

function persist(): void {
  const store = storage()
  if (!store) return
  try {
    // 只保留最近的一批，避免无限增长
    const entries = Array.from(answeredGroups.entries()).slice(-MAX_ENTRIES)
    store.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(entries)))
  } catch {
    // 配额满或被禁用时静默降级为内存记录。
  }
}

export function rememberAnsweredGroup(groupId: string, answers: AnswerMap): void {
  if (!groupId) return
  hydrate()
  answeredGroups.set(groupId, { ...answers })
  persist()
}

export function answeredGroupAnswers(groupId: string): AnswerMap | null {
  if (!groupId) return null
  hydrate()
  const stored = answeredGroups.get(groupId)
  return stored ? { ...stored } : null
}

/** 仅用于测试复位，不要在运行期调用。 */
export function resetAnsweredGroups(): void {
  answeredGroups.clear()
  hydrated = true
  const store = storage()
  try {
    store?.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}
