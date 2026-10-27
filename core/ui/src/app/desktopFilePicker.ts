import { createDomFilePicker, type RuntimeFileCapabilities } from './runtime'

// user:“修”+(桌面资料库保留字节选择，聊天附件独立使用原生选择器返回原件路径)。
export function createDesktopFilePicker(pickPaths: () => Promise<string[] | null>): RuntimeFileCapabilities {
  return { ...createDomFilePicker(), pickPaths }
}
