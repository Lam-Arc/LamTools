// Smoke beat: the smallest real turn — new session, pick a model, type, send,
// wait for the answer.  It exists to prove the whole chain (window driving →
// record proxy → capture) before any long beat is attempted.

import { newSession, pickModel, askPrompt, DEFAULT_MODEL } from './_lib.mjs'

export const meta = {
  name: 'smoke',
  title: '最小闭环',
  description: '新建会话 → 选模型 → 输入 → 发送 → 等待回答',
}

export async function run(ctx) {
  const { actor, hold } = ctx

  await newSession(ctx)
  await hold(600)

  await pickModel(ctx, { model: DEFAULT_MODEL })
  await hold(400)

  await askPrompt(ctx, '用一句话说明你现在能帮我做什么', { delay: 55 })

  await actor.move('.composer-input-wrap textarea', { label: '回到输入框' })
  await hold(900)
}
