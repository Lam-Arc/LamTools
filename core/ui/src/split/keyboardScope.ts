import { inject, type InjectionKey, type Ref } from 'vue'
import { useOptionalWorkspace } from '@/workspace/context'
export const SplitKeyboardScopeKey: InjectionKey<Ref<boolean>> = Symbol('split-keyboard-scope')
// user:“多界面分屏”+(同时挂载的页面只能响应本屏的键盘操作，后台标签不一起返回或关闭)。
export function useSplitKeyboardScope() {
  const local = inject(SplitKeyboardScopeKey, null), workspace = useOptionalWorkspace()
  return () => local ? local.value : !workspace || workspace.state.hidden || workspace.state.activePane === 'main'
}
