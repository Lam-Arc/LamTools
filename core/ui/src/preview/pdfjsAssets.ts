/**
 * pdfjs 的字体资源位置（唯一一份）。
 *
 * user:“除了Office类，别的都把它修好”+(中文 PDF 常用非嵌入的 CID 字体，缺 cMap 时整页空白；
 * 标准字体数据同理。这些文件随界面一起发布在 `/pdfjs/` 下，离线可用，不连 CDN)。
 *
 * 文件来源：`node_modules/pdfjs-dist/cmaps`、`node_modules/pdfjs-dist/standard_fonts`
 * 的副本（放在 `core/ui/public/pdfjs/`），升级 pdfjs 时一起更新。
 */
export const PDFJS_ASSET_OPTIONS = {
  cMapUrl: '/pdfjs/cmaps/',
  cMapPacked: true,
  standardFontDataUrl: '/pdfjs/standard_fonts/',
} as const
