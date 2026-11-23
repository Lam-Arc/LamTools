// user:“favicon 进标签栏”+(标签栏渲染在布局层，拿不到浏览器组件的局部状态，所以图标放一个共享 store；
// 缓存与退化链不变：原生 favicon → 脚本读 <link rel=icon> → 首字母占位)。
import { reactive } from 'vue'

const icons = reactive<Record<string, string>>({})

/** 写一次图标；空值等于清掉（避免换成无图标站点后还显示上一个站点的图标）。 */
export function setBrowserTabIcon(id: string, icon?: string | null): void {
  if (icon) icons[id] = icon
  else delete icons[id]
}

export function forgetBrowserTabIcon(id: string): void {
  delete icons[id]
}

export function browserTabIcon(id: string): string | undefined {
  return icons[id]
}

/** 退化到最后一级：标题的首个「字母/数字/汉字」，都没有就用一个中性点。 */
export function browserTabInitial(title: string): string {
  for (const char of title.trim()) {
    if (/[\p{L}\p{N}]/u.test(char)) return char.toUpperCase()
  }
  return '•'
}
