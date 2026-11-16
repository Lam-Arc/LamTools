import { createApp, h, ref } from 'vue'
import SundaySwitch from '@/components/SundaySwitch.vue'
import UiSelect from '@/components/UiSelect.vue'
import selectStyles from '@/styles/ui-select.css?inline'
import pluginStyles from '../../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/style.css?inline'
import switchStyles from '@/styles/sunday-switch.css?inline'
import variables from '@/styles/variables.css?inline'

// user:“确保视觉、功能和交互不退化”+(模拟独立插件注入共享样式，不依赖宿主页面样式)。
const style = document.createElement('style')
style.textContent = variables + pluginStyles + switchStyles + selectStyles
document.head.append(style)
const host = document.createElement('div')
host.id = 'network-switch-fixture'
host.className = 'nx-app'
document.body.replaceChildren(host)
createApp({ setup() {
  const value = ref(false)
  const selected = ref('one')
  return () => h('div', [
    h(SundaySwitch, { modelValue: value.value, label: '网络开关示例', 'onUpdate:modelValue': (next: boolean) => { value.value = next } }),
    h('div', { class: 'nx-quick-app' }, [h('div', { class: 'nx-node-wrap' }, [h(UiSelect, { modelValue: selected.value, ariaLabel: '网络下拉示例', options: [{ value: 'one', label: '第一项' }, { value: 'two', label: '第二项' }], 'onUpdate:modelValue': (next: string) => { selected.value = next } })])]),
  ])
} }).mount(host)

