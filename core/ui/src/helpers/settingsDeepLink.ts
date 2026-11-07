/**
 * 设置工作台直达（托盘/右键 → 主窗口设置分区 + 对象 ID）。
 *
 * user:“托盘‘桌宠设置’、桌宠右键‘编辑角色’、Ping 菜单‘设置此项’可直达对应
 * 工作台、选中对象”+
 * (跨窗口只传稳定 ID；页面可能尚未挂载，所以同时写入短期 localStorage，
 *  已挂载的页面再通过同窗口 CustomEvent 立即响应。)
 */
export type SettingsDeepLinkSection = 'pet' | 'ping'

export interface SettingsDeepLink {
  section: SettingsDeepLinkSection
  objectId: string
  at: number
}

const STORAGE_KEY = 'lamtools.core.settings.deep-link'
const EVENT_NAME = 'lamtools:settings-deep-link'
const MAX_AGE_MS = 60_000

export function publishSettingsDeepLink(section: SettingsDeepLinkSection, objectId = ''): void {
  const link: SettingsDeepLink = { section, objectId: String(objectId || ''), at: Date.now() }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(link))
  } catch {
    // 隐私模式/存储被禁用：同窗口事件仍然可用。
  }
  window.dispatchEvent(new CustomEvent<SettingsDeepLink>(EVENT_NAME, { detail: link }))
}

/** 页面挂载时取一次；过期或分区不匹配返回空对象。 */
export function consumeSettingsDeepLink(section: SettingsDeepLinkSection): string {
  let objectId = ''
  try {
    const text = localStorage.getItem(STORAGE_KEY)
    if (!text) return ''
    const link = JSON.parse(text) as SettingsDeepLink
    const expired = Date.now() - Number(link?.at || 0) > MAX_AGE_MS
    if (expired) {
      localStorage.removeItem(STORAGE_KEY)
      return ''
    }
    // 分区不匹配时保留记录：另一个工作台挂载时还要读它。
    if (link?.section !== section) return ''
    objectId = String(link.objectId || '')
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 坏数据直接当作没有直达目标。
  }
  return objectId
}

export function onSettingsDeepLink(
  section: SettingsDeepLinkSection,
  handler: (objectId: string) => void,
): () => void {
  const listener = (event: Event): void => {
    const detail = (event as CustomEvent<SettingsDeepLink>).detail
    if (detail?.section !== section) return
    // 事件到达说明页面已挂载：顺手清掉挂载时用的短期存储，避免下次重进重复选中。
    const pending = consumeSettingsDeepLink(section)
    handler(pending || String(detail.objectId || ''))
  }
  window.addEventListener(EVENT_NAME, listener)
  return () => window.removeEventListener(EVENT_NAME, listener)
}
