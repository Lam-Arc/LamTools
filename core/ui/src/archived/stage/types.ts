/**
 * 已归档：视窗（Stage pane）的类型。
 *
 * 2026-10 随视窗整体归档——成果与文件都改走系统默认应用打开，聊天内自带
 * 图片预览与 Markdown 渲染，视窗不再有入口。类型随组件保存在这里，
 * 仅供归档组件内部引用；不要在活跃代码里 import。
 */

export type StageKind = 'code' | 'image' | 'video' | 'audio' | 'pdf' | 'browser' | 'markdown' | 'empty';

export interface StageResource {
  id: string;
  kind: StageKind;
  path?: string;
  url?: string;
  language?: string;
  label?: string;
  content?: string;
  previewMode?: 'code' | 'preview';
}
