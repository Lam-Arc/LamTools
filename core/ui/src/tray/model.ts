/**
 * 托盘面板的纯文案模型。
 *
 * user:“上面不需要标题和状态，多此一举了”“这个东西不需要小字，看着很多余”+
 * (面板只留能点的四行：图标加标签，开关跟着真实状态走。)
 */

export interface TrayState {
  /** 桌宠覆盖层当前是否真的显示着。 */
  petOpen: boolean
  /** 桌面标注层当前是否真的显示着。 */
  overlayOpen: boolean
}

export type TrayRowKind = 'action' | 'toggle' | 'danger'

export interface TrayRow {
  id: 'main' | 'pet' | 'overlay' | 'quit'
  title: string
  kind: TrayRowKind
  /** 只有 toggle 有：开关当前值。 */
  value?: boolean
}

export function trayRows(state: TrayState): TrayRow[] {
  return [
    { id: 'main', title: '打开界面', kind: 'action' },
    { id: 'pet', title: '桌宠', kind: 'toggle', value: state.petOpen },
    { id: 'overlay', title: '交互层', kind: 'toggle', value: state.overlayOpen },
    { id: 'quit', title: '退出', kind: 'danger' },
  ]
}
