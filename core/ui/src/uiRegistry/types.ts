/**
 * 可编辑界面的注册表类型。
 *
 * user:“新增核心功能：主题设置 → 可视化界面编辑器”+
 * (编辑器不能从任意 DOM 推断可编辑能力，必须先有一套稳定的元素身份与可改字段声明。
 *  这里只定义类型，不参与运行时渲染。)
 */

/** 可编辑的属性类别，刻意保持有限枚举，避免编辑器无限膨胀。 */
export type UiEditableProperty =
  | 'position'
  | 'size'
  | 'spacing'
  | 'radius'
  | 'border'
  | 'color'
  | 'background'
  | 'text'
  | 'opacity'
  | 'layer'
  | 'visibility'

/** 保护级别：能不能改、能改多少。 */
export type UiProtectionLevel = 'editable' | 'appearance-only' | 'protected'

export interface UiRegistryEntry {
  /** 稳定标识，格式为 `区域.名称`，全表唯一；元素落到 data-ui-id，模板落到 data-ui-template。 */
  id: string
  /** 元素是唯一节点，模板是重复出现的同类节点（如会话行、消息行）。 */
  kind?: 'element' | 'template'
  /** 面向用户的名称，用于图层树与属性面板标题。 */
  label: string
  /** 拥有该元素的组件文件，相对 core/ui/src。 */
  owner: string
  /** 父级元素的标识；顶层元素留空。 */
  parent?: string
  /** 允许编辑的属性类别。 */
  properties: UiEditableProperty[]
  /** 保护级别：editable 可改外观与尺寸；appearance-only 只允许外观；protected 不允许改。 */
  protection: UiProtectionLevel
  /** 给编辑器的补充说明，例如“业务关键入口，禁止隐藏”。 */
  note?: string
}
