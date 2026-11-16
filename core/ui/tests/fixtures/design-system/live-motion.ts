import layoutStyles from '@/styles/layout.css?inline'
const style = document.createElement('style')
style.textContent = layoutStyles
document.head.append(style)
for (const className of ['assistant-message--live', 'process-stream--live']) {
  const element = document.createElement('div')
  element.className = className
  element.textContent = '示例消息'
  document.body.append(element)
}
