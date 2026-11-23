/**
 * 交互相位（V2-C2 收口）。
 *
 * user:“让位改为单一登记口…交互相位只影响会重排布局的手势”+
 * (类型原来长在已下线的旧拖拽模块里；旧内核下线后，保留模块 browserVisibility.ts 仍需要它，
 *  所以只把这一个类型搬进 workspace，不再拖带整套拖拽状态机。)
 */
export type InteractionPhase = 'none' | 'resizing' | 'draggingTab' | 'splitPulling' | 'swapping'

/** 切标签时旧网页隐藏到新网页显示之间留的观察时间。 */
export const TAB_SWITCH_GAP = 80
