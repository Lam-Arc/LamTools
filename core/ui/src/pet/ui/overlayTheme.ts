/**
 * 覆盖层主题：与主界面同一份偏好、同一套主题变量。
 *
 * user:“把样式也对齐，这是第一步”
 * +(桌宠覆盖层是独立文档，之前只有一组静态 --pet-glass，不跟主界面主题走。
 *   这里复用 useCoreUiPreferences（与主界面同一个 localStorage 键）、
 *   themeToCSSVars（与 WorkspaceShell 同一个变量生成器）和
 *   applyStoredPublishedTheme（与主界面启动同一条主题工作室应用路径），
 *   覆盖层不另立任何颜色系统；主窗口改主题时经 storage 事件即时跟随。)
 */
import { onMounted, onUnmounted, watch } from 'vue'
import { useCoreUiPreferences } from '@/composables/useCoreUiPreferences.ts'
import { themeToCSSVars } from '@/helpers/theme.ts'
import { applyStoredPublishedTheme } from '@/themeStudio/bootstrap.ts'
import { THEME_STUDIO_STORAGE_KEY } from '@/themeStudio/constants.ts'

/** 主界面 UI 偏好的存储键（LamToolsApp 使用的同一个键）。 */
export const CORE_UI_PREFERENCES_STORAGE_KEY = 'lamtools.core.ui.preferences'

export function useOverlayTheme(): void {
  const preferences = useCoreUiPreferences(CORE_UI_PREFERENCES_STORAGE_KEY)
  let appliedKeys: string[] = []

  function applyThemeVariables(): void {
    if (typeof document === 'undefined') return
    const root = document.documentElement
    for (const key of appliedKeys) root.style.removeProperty(key)
    appliedKeys = []
    for (const [key, value] of Object.entries(themeToCSSVars(preferences.theme.value))) {
      root.style.setProperty(key, value)
      appliedKeys.push(key)
    }
  }

  function applyPublishedTheme(): void {
    // 主题工作室发布的样式沿用主界面启动时的同一个应用函数（幂等：固定 style 元素）。
    applyStoredPublishedTheme()
  }

  function onStorage(event: StorageEvent): void {
    if (event.key === CORE_UI_PREFERENCES_STORAGE_KEY || event.key === null) {
      void preferences.load().then(applyThemeVariables)
    }
    if (event.key === THEME_STUDIO_STORAGE_KEY || event.key === null) applyPublishedTheme()
  }

  onMounted(() => {
    // 先铺默认主题再异步读偏好：首帧就有令牌，不会出现一段无色窗口。
    applyThemeVariables()
    void preferences.load().then(applyThemeVariables)
    applyPublishedTheme()
    window.addEventListener('storage', onStorage)
  })

  onUnmounted(() => {
    window.removeEventListener('storage', onStorage)
  })

  watch(() => preferences.theme.value, applyThemeVariables)
}
