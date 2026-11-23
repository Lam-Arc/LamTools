/**
 * 「引用」：把一张图当成附件塞进输入框的通道。
 *
 * user:“『引用』，直接将已标注/未标注则为原图直接加入输入框，等价与复制再粘贴”+
 * (粘贴图片走的是输入框自己的上传管线：它同时维护文本引用与附件托盘，
 *  两者是同一份事实的两份投影。所以这里不自己拼上传请求，只把文件交给宿主，
 *  由宿主复用 `uploadFiles`，效果与用户真的粘贴一张图完全一致。)
 *
 * user:“现在本身就是存路径，可以直接把路径上传上去，走路径那条链路”+
 * (灯箱里的图本来就是磁盘文件时，只交绝对路径：输入框走 `/attachments/reference`
 *  那条登记链，不读字节、不复制文件、也不经过 fetch；只有“刚标注出来的新图”
 *  没有路径，才退回字节上传。)
 *
 * 灯箱是被浮层托管的单例，拿不到输入框的内部状态，因此用注入：宿主提供能力，
 * 没有宿主（展厅、独立窗口）时按钮不出现，而不是点了没反应。
 */
import type { InjectionKey } from 'vue'

/** 本机文件引用：只带路径，由输入框侧走“登记路径”的那条链。 */
export interface PreviewComposerPath {
  path: string
  name: string
}

export interface PreviewComposerBridge {
  /** 等同于用户把这张图粘贴进输入框：文件或路径引用都接受。 */
  attach(items: (File | PreviewComposerPath)[]): Promise<void>
  /** 当前有没有能接收附件的会话（没有会话时按钮应禁用）。 */
  canAttach(): boolean
  /**
   * 把一段原文放进输入框（分屏里选中文档内容后“引用给 Agent”）。
   *
   * user:“分屏预览的能力应该要比灯箱更多”+(灯箱是看完即关，不需要带走文字；
   * 分屏常驻，看文档时把一段原文递给输入框才是它该有的能力。走的是粘贴那段文字，
   * 不是附件通道)。
   */
  insert?(text: string): void
}

export const PREVIEW_COMPOSER_KEY: InjectionKey<PreviewComposerBridge> = Symbol('lamtools-preview-composer')
