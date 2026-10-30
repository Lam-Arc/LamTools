/**
 * 主题文档模型的对外入口。
 *
 * user:“可视化主题与布局编辑器”+
 * (运行端只读已发布文档，编辑器写草稿；两者共用同一套类型与校验。)
 */
export {
  THEME_STUDIO_SCHEMA_VERSION,
  createEmptyStudioDocument,
  type StudioAsset,
  type StudioBackground,
  type StudioBackgroundFit,
  type StudioBackgroundOverflow,
  type StudioBreakpoint,
  type StudioDimension,
  type StudioDocument,
  type StudioGradientStop,
  type StudioNodeStyle,
  type StudioSize,
  type StudioSizeMode,
  type StudioSpacing,
  type StudioText,
} from './schema.ts'

export { validateStudioDocument, type StudioIssue, type StudioValidationResult } from './validate.ts'
export { migrateStudioDocument, type StudioMigrationResult } from './migrate.ts'
export { compileStudioDocument, selectorFor, templateSelectorFor, instanceSelectorFor, type CompileOptions } from './compile.ts'
export { applyStoredPublishedTheme, type ApplyStoredThemeOptions } from './bootstrap.ts'
