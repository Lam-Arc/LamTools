/**
 * 滑条对照：把项目里两套滑条放到同一块底上，看它们到底是不是一回事。
 *
 * user:“思考的滑动条是不是一个可复用样式？与配套的卡片与动画？”+
 * (先确认竖向思考滑条与横向通用滑条是两套实现，再谈能不能合成一套)。
 */
import { createApp, h, ref } from 'vue'
import ThinkingIntensitySlider from '@/components/ThinkingIntensitySlider.vue'
import SundayRange from '@/components/SundayRange.vue'
import '@/styles/variables.css'
import '@/styles/base.css'
import '@/styles/sunday-controls.css'

const THINKING = [
  { value: 'off', label: '关闭' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'max', label: '极限' },
]

createApp({
  setup() {
    const thinking = ref('medium')
    const size = ref(32)
    return () => h('div', { class: 'thinking-lab' }, [
      h('section', { class: 'card' }, [
        h('h2', {}, '竖向思考滑条 · ThinkingIntensitySlider'),
        h('p', { class: 'hint' }, '584 行，绑定思考等级语义，带刻度、拖拽、键盘、极限档粒子'),
        h('div', { class: 'stage' }, [
          h('div', { class: 'slider-slot' }, [
          h(ThinkingIntensitySlider, {
            modelValue: thinking.value,
            options: THINKING,
            label: '思考强度',
            'onUpdate:modelValue': (value: string) => { thinking.value = value },
          }),
          ]),
        ]),
      ]),
      h('section', { class: 'card' }, [
        h('h2', {}, '横向通用滑条 · SundayRange'),
        h('p', { class: 'hint' }, '74 行，标签 + 数值 + 轨道 + 原生 range，设置页在用'),
        h('div', { class: 'stage' }, [
          h(SundayRange, {
            modelValue: size.value,
            min: 12,
            max: 64,
            step: 1,
            label: '头像尺寸',
            'onUpdate:modelValue': (value: number) => { size.value = value },
          }),
        ]),
      ]),
    ])
  },
}).mount('#app')
