// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(主设置与独立桌宠窗口共用真实遮挡及几何精度选项)
export const petQualityOptions = [
  { value: 'low', label: '低（更快，线段更少）' },
  { value: 'balanced', label: '均衡' },
  { value: 'high', label: '高（更贴边缘）' },
] as const
export const petZModeOptions = [
  { value: 'top', label: '置顶（总在窗口之上）' },
  { value: 'clip', label: '置顶 + 按窗口几何裁剪（推荐）' },
  { value: 'behind', label: '压到窗口之下（整层被挡）' },
] as const
