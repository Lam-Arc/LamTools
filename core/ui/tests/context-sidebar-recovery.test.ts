// user:“这个会话已经跑了很久了，不可能没有上下文”+(恢复期间没有助手正文时，也保留后台已有的上下文读数)。
import { expect, it } from 'vitest'
import { hydrateSnapshot, selectChatMessages } from '../src/appServer'
import { buildCoreResourceSummary } from '../src/runtime/resources'

it.each([['usage', 731351], ['estimate', 67000]] as const)(
 'retains %s context while restored turn is waiting for its first assistant item', (source, tokens) => {
  const metrics = {context_tokens:tokens, context_window_tokens:868928, context_measurement_source:source}
  const snapshot=hydrateSnapshot({
   thread_id:'thread',snapshot_seq:3,status:'running',
   turns:{turn:{turn_id:'turn',status:'running',items:['user']}},
   items:{user:{item_id:'user',turn_id:'turn',type:'userMessage',status:'completed',content:'继续'}},
   item_order:['user'],
   core:{thread_id:'thread',snapshot_seq:3,status:'running',items:{},item_order:[],
    turns:{turn:{turn_id:'turn',status:'running',items:[],context_metrics:metrics}}},
  })
  const messages=selectChatMessages(snapshot)
  expect(messages.at(-1)?.metadata?.initialWaiting).toBe(true)
  const summary=buildCoreResourceSummary(messages)
  expect(summary?.hasContext).toBe(true)
  expect(summary?.currentRatio).toBeCloseTo(tokens/868928)
  expect(summary?.contextLabel).toContain(source==='usage'?'实测':'估算')
 })
