/**
 * 标注的绘制（唯一一份）。
 *
 * user:“复用ping的框选那里的标注功能与样式”+(逐字搬自 Ping 截图编辑器的 `drawAnnotation`：
 * 笔画粗细、箭头三角、问号叹号圆环、文字半透明底都保持原样，因此两个宿主画出来一模一样。)
 *
 * 这里只有 Canvas 2D：不读 DOM、不认主题，输入是「图片像素坐标 + 图片宽度」。
 * 字号与线宽都按图片宽度推导，所以同一份标注在缩略和放大时比例一致，
 * 导出的成图也和屏幕上看到的一致。
 */
import type { Annotation } from './model'

/** 标注尺寸：跟着图片宽度走，最小 22px、最大 64px（图片像素）。 */
export function annotationSize(imageWidth: number): number {
  return Math.max(22, Math.min(64, (imageWidth || 0) * 0.03))
}

/**
 * 画一条标注。
 *
 * @param imageWidth 整张图片的宽度（像素），用来推导字号与线宽。
 */
export function drawAnnotation(context: CanvasRenderingContext2D, annotation: Annotation, imageWidth: number): void {
  const size = annotationSize(imageWidth)
  context.save()
  context.strokeStyle = annotation.color
  context.fillStyle = annotation.color
  context.lineWidth = Math.max(3, size * 0.12)
  context.lineCap = 'round'
  context.lineJoin = 'round'
  if (annotation.tool === 'question' || annotation.tool === 'exclamation') {
    const point = annotation.points[0]
    if (point) {
      context.beginPath()
      context.arc(point.x, point.y, size * 0.7, 0, Math.PI * 2)
      context.stroke()
      context.font = `${Math.round(size)}px system-ui, sans-serif`
      context.textAlign = 'center'
      context.textBaseline = 'middle'
      context.fillText(annotation.tool === 'question' ? '?' : '!', point.x, point.y)
    }
  } else if (annotation.tool === 'arrow') {
    const [start, end] = annotation.points
    if (start && end) {
      context.beginPath()
      context.moveTo(start.x, start.y)
      context.lineTo(end.x, end.y)
      context.stroke()
      const angle = Math.atan2(end.y - start.y, end.x - start.x)
      const head = size * 0.6
      context.beginPath()
      context.moveTo(end.x, end.y)
      context.lineTo(end.x - head * Math.cos(angle - 0.4), end.y - head * Math.sin(angle - 0.4))
      context.lineTo(end.x - head * Math.cos(angle + 0.4), end.y - head * Math.sin(angle + 0.4))
      context.closePath()
      context.fill()
    }
  } else if (annotation.tool === 'text') {
    const point = annotation.points[0]
    if (point) {
      context.font = `${Math.round(size * 0.62)}px system-ui, sans-serif`
      context.textAlign = 'left'
      context.textBaseline = 'top'
      const text = annotation.text || '文字'
      const metrics = context.measureText(text)
      context.fillStyle = 'rgba(8, 10, 14, 0.72)'
      context.fillRect(point.x - 4, point.y - 4, metrics.width + 10, size * 0.9)
      context.fillStyle = annotation.color
      context.fillText(text, point.x, point.y)
    }
  } else {
    context.beginPath()
    annotation.points.forEach((point, index) => {
      if (index === 0) context.moveTo(point.x, point.y)
      else context.lineTo(point.x, point.y)
    })
    context.stroke()
  }
  context.restore()
}

/** 画一批标注（顺序即层序）。 */
export function drawAnnotations(context: CanvasRenderingContext2D, annotations: readonly Annotation[], imageWidth: number): void {
  for (const annotation of annotations) drawAnnotation(context, annotation, imageWidth)
}
