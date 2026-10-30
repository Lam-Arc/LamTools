/**
 * 主题编辑器的常量。
 *
 * user:“主题保存、导入导出与恢复机制”+
 * (发布版本单独存一个键；安全模式只清这一份，不影响其它偏好。)
 */

export const THEME_STUDIO_STORAGE_KEY = 'sunday.themeStudio.published.v1'

/**
 * user:“按这个设计方案审…补齐”+(方案 §10.1 自动保存草稿：草稿单独存一个键，
 *  重开编辑器接着上次编辑；发布/取消/恢复默认时清除。)
 */
export const THEME_STUDIO_DRAFT_STORAGE_KEY = 'sunday.themeStudio.draft.v1'
