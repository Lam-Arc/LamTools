import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { selectCoreSubAgentRun } from '@/agents/subAgentProjection'
import { selectCoreWorkbenchMessages } from '@/appServer/workbenchProjection'
import { hydrateSnapshot } from '@/appServer/snapshot'
import type { CoreAppSnapshot } from '@/appServer/protocol'
import type { CoreMessage, CoreSubAgentRun } from '@/types'
import type { LamToolsTransport } from '@/transport'
import type { SplitTab } from './layout'
// user:“多界面分屏”+(子代理绑定来源聊天，主屏切换后仍读来源记录，绝不匹配新聊天中的同名代理)。
export function useSplitAgent(props: { tab: SplitTab; visible: boolean; messages: CoreMessage[]; activeSessionId: string; transport: LamToolsTransport }) {
  const cached = shallowRef<CoreSubAgentRun>(), error = ref(''), loading = ref(false)
  const current = computed(() => props.tab.sessionId === props.activeSessionId)
  const run = computed(() => {
    if (props.tab.kind !== 'agent') return undefined
    if (current.value) return selectCoreSubAgentRun(props.messages, { subSessionId: props.tab.resource, name: props.tab.title }) || cached.value
    return cached.value
  })
  watch(run, value => { if (value) cached.value = value }, { immediate: true })
  let timer: ReturnType<typeof setTimeout> | undefined, abort: AbortController | undefined, generation = 0
  function stop() { clearTimeout(timer); abort?.abort(); generation++ }
  async function refresh() {
    stop()
    // user:“审查分屏代码，并优化”+(切回来源聊天后旧的读取失败提示必须消失，不能盖住正在更新的实时过程)。
    error.value = ''; loading.value = false
    if (props.tab.kind !== 'agent' || current.value || !props.visible || !props.tab.sessionId) return
    const token = generation; abort = new AbortController(); loading.value = true; error.value = ''
    try {
      const response = await props.transport.request<{ snapshot?: CoreAppSnapshot }>({ kind: 'rpc', method: 'thread/read', params: { thread_id: props.tab.sessionId }, signal: abort.signal, timeoutMs: 15000 })
      if (token !== generation) return
      if (!response.snapshot || response.snapshot.thread_id !== props.tab.sessionId) throw Error('来源聊天记录暂不可用')
      const projected = selectCoreWorkbenchMessages(hydrateSnapshot(response.snapshot))
      const result = selectCoreSubAgentRun(projected, { subSessionId: props.tab.resource, name: props.tab.title })
      if (result) cached.value = result
      else error.value = '这页历史中没有该子代理的过程，可回到来源聊天查看'
      if (result && ['running','waiting','pending'].includes(result.status)) timer = setTimeout(refresh, 4000)
    } catch (cause) { if (token === generation) error.value = String(cause) }
    finally { if (token === generation) loading.value = false }
  }
  watch(() => [props.tab.kind, props.tab.sessionId, props.activeSessionId, props.visible], refresh, { immediate: true })
  onBeforeUnmount(stop)
  return { run, current, error, loading, refresh }
}
