/**
 * 胶囊预览页：把整页当成一块屏幕，直接挂共享组件 ComputerUseCapsule。
 * user:“给 agent 的鼠标样式你是怎么设计的？给我看看？”+
 * (深色底和浅色底各放一枚 Agent 光标实样，大小和对比度直接看。)
 */
import { createApp, h } from 'vue'
import ComputerUseCapsule from '@/computerUse/ComputerUseCapsule.vue'
import ComputerUseCursor from '@/computerUse/ComputerUseCursor.vue'

createApp({
  setup() {
    const paperLeft = () => Math.round(window.innerWidth * 0.62)
    return () => {
      const left = paperLeft()
      return h('div', { class: 'preview-root' }, [
        h(ComputerUseCapsule, { onStop: () => {} }),
        h('div', { class: 'preview-content' }, [
          h('h1', 'Computer Use 屏幕胶囊'),
          h('p', '这块页面代表整块屏幕：四边是一圈 2px 呼吸流光，四角外沿贴屏幕角、内侧 6px 圆弧。'),
          h('p', '下面两枚是 Agent 自己的光标实样，深色底和浅色底各一枚，尺寸 23×27px。'),
        ]),
        h(ComputerUseCursor, { x: left - 180, y: 330 }),
        h('div', { class: 'preview-paper', style: { left: `${left}px` } }),
        h(ComputerUseCursor, { x: left + 130, y: 330 }),
      ])
    }
  },
}).mount('#bar-preview')
