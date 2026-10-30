import { ref } from 'vue'

/**
 * 界面编辑器打开状态（应用级单例）。
 *
 * user:“我只要切换界面，编辑就自动取消了，那它不是永远不可能编辑到主界面吗”+
 * (编辑器挂到应用层而不是设置页：打开状态放全局单例，
 *  从设置页点开后再切到聊天、资料库等任何界面，编辑都不中断，走到哪改到哪。)
 */
const studioOpen = ref(false)

export function useThemeStudio() {
  return { studioOpen }
}
