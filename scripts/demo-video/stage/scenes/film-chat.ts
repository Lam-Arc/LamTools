/* 办公段的中栏：真实聊天，按 520 宽渲染（界面是响应式的，窄了它自己重排）。 */

import { reveal, type StageScene } from '../src/timeline'
import { snapshotAt } from '../src/snapshot'
import { BASE, PROJECT, SESSION, PROMPT, TYPE_FROM, TYPE_CPS, SEND_AT, TURNS } from './_film-office-parts'

export default {
  id: 'film-chat',
  duration: 16,

  frame() {
    return { rect: { x: 0, y: 0, w: 520, h: 888, radius: 0 }, overlay: '', caption: { title: '', hint: '' } }
  },

  data(t, revision) {
    return {
      projects: [PROJECT],
      sessions: [SESSION],
      threadId: SESSION.id,
      theme: 'light' as const,
      composerDraft: t < SEND_AT ? reveal(PROMPT, t, TYPE_FROM, TYPE_CPS) : '',
      snapshot: snapshotAt(TURNS, t, { threadId: SESSION.id, revision, baseTime: BASE, idPrefix: 'film-chat' }),
    }
  },
} satisfies StageScene
