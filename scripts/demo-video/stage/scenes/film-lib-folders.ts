/* 办公段的左栏：真实资料库，按 380 宽渲染（分层视图）。 */

import { type StageScene } from '../src/timeline'
import { officeData, useLibrary } from './_film-office-parts'

export default {
  id: 'film-lib-folders',
  duration: 4,

  frame(t) {
    useLibrary(t, '文件夹')
    return { rect: { x: 0, y: 0, w: 380, h: 888, radius: 0 }, overlay: '', caption: { title: '', hint: '' } }
  },

  data(t, revision) {
    return officeData(t, revision, 'film-lib-folders')
  },
} satisfies StageScene
