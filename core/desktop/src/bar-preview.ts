/**
 * 胶囊预览页：只挂 ComputerUseBar，状态由页面自己切，不连后端。
 */
import { createApp, h, ref } from 'vue'
import ComputerUseBar from '@/components/ComputerUseBar.vue'

const state = ref<'running' | 'paused'>('running')

createApp({
  setup() {
    return () =>
      h('div', { class: 'preview-root' }, [
        h('div', { class: 'preview-window-edge' }),
        h(ComputerUseBar, { previewState: state.value }),
        h('div', { class: 'preview-content' }, [
          h('h1', 'Computer Use 状态胶囊'),
          h('p', '窗口四周是一圈 2px 呼吸流光，胶囊坐在上沿正中，两者颜色和节奏同源，胶囊与边框交界处连续成一整条线。'),
          h('p', '两个按钮分别是暂停/继续和结束，没有其它文字。'),
        ]),
        h('div', { class: 'preview-controls' }, [
          h(
            'button',
            {
              onClick: () => {
                state.value = state.value === 'running' ? 'paused' : 'running'
              },
            },
            state.value === 'running' ? '切到暂停态' : '切到运行态',
          ),
        ]),
      ])
  },
}).mount('#bar-preview')
