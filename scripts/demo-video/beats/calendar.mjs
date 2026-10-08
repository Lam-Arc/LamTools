// Calendar beat: the flagship "code editing" scene.
//
// One real task — build a calendar app with a considered visual language — so
// the video has a concrete, judgeable artifact at the end of the agent run.

import { newSession, pickModel, typePrompt, DEFAULT_MODEL } from './_lib.mjs'

export const meta = {
  name: 'calendar',
  title: '日历应用',
  description: '从一句需求到可用的日历应用，重点在成品的界面质感',
}

/**
 * Prompts stay short and conversational on purpose.
 *
 * A long, numbered spec makes the demo look like the prompt did the work.
 * The task should read like something a person actually types, and whatever
 * planning, checklists or delegation happen should look like the agent's own
 * decision.  (A "single file, no dependencies" clause was an earlier mistake:
 * it gave the model a reason to skip planning and work alone.)
 */
export const PROMPT = `帮我做个日历应用，我想天天用，所以得好看、有质感。

要能看整月、能记日程，顶部最好一眼看出哪个月最忙。键盘也能用起来。`

export async function run(ctx) {
  const { actor, page, hold, waitTurn, note } = ctx

  await newSession(ctx)
  await hold(500)
  await pickModel(ctx, { model: DEFAULT_MODEL })
  await hold(300)

  // Full access keeps a long autonomous run from stalling on an approval card.
  const runtimeText = (await page
    .locator('.core-runtime-menu, .composer-model-row')
    .first()
    .innerText()
    .catch(() => '')) || ''
  note(`composer controls: ${runtimeText.replace(/\s+/g, ' ').slice(0, 60)}`)
  if (!runtimeText.includes('完全访问')) {
    throw new Error(
      `permission preset is not full access — the run would stall on approvals (saw: ${runtimeText.replace(/\s+/g, ' ').slice(0, 60)})`,
    )
  }

  await typePrompt(ctx, PROMPT, { delay: 18, send: true })
  note('prompt sent; waiting for the run to finish')
  await waitTurn(page)
  note('run finished')

  await hold(1200)
  await actor.move('.composer-input-wrap textarea', { label: '回到输入框' })
}
